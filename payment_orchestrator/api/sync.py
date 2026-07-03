import frappe
from frappe.utils import add_to_date, cint, flt, now_datetime

from payment_orchestrator.logic import (
    allocate_available_amount,
    apply_unpaid_terminal_provider_status,
    refresh_intent_and_reference,
)
from payment_orchestrator.services import update_reference_payment_summary
from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.utils import get_settings


def run_periodic_sync():
    settings = get_settings()

    stale_intents = frappe.get_all(
        'Payment Intent',
        filters={'status': ['in', ['Requested', 'Paid', 'Partially Allocated']]},
        fields=['name', 'provider_link_id', 'provider_qr_id', 'provider_payment_id'],
        limit=100,
    )

    for row in stale_intents:
        try:
            intent = frappe.get_doc('Payment Intent', row.name)
            if row.provider_link_id:
                fetch_payment_link_for_gateway(intent)
                intent.reload()
            if row.provider_qr_id:
                client = RazorpayClient(settings=settings, mode=intent.provider_mode or 'Test')
                data = client.fetch_qr_code(row.provider_qr_id)
                if not apply_unpaid_terminal_provider_status(intent, data.get('status'), data):
                    intent.db_set('qr_status', data.get('status'))
                    intent.db_set('payment_status', data.get('status'))
                    intent.db_set('last_synced_on', now_datetime())
            if intent.gateway == 'Pine Labs' and intent.payment_mode == 'POS' and intent.provider_pos_request_id:
                sync_pinelabs_pos_status(intent, settings)
                intent.reload()
            payment_entry = frappe.db.get_value('Payment Entry', {'reference_no': ['in', [intent.provider_payment_id, intent.name]]}, 'name')
            if payment_entry and cint(settings.enable_auto_allocation):
                allocate_available_amount(intent, payment_entry)
                refresh_intent_and_reference(intent)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f'Payment Orchestrator sync failed for {row.name}')

    _expire_stale_unpaid_intents()


def fetch_payment_link_for_gateway(intent):
    if intent.gateway == 'Pine Labs':
        from payment_orchestrator.api.pinelabs import fetch_payment_link
    else:
        from payment_orchestrator.api.razorpay import fetch_payment_link

    return fetch_payment_link(intent.name)


def sync_pinelabs_pos_status(intent, settings=None):
    from payment_orchestrator.api.pinelabs import (
        apply_pos_success,
        apply_pos_terminal_failure,
        is_pos_approved,
        is_pos_terminal_failure,
    )
    from payment_orchestrator.provider.pinelabs.pos import PineLabsPOSAdapter

    response = PineLabsPOSAdapter(settings=settings or get_settings()).fetch_status(intent)
    if is_pos_approved(response) and not intent.provider_payment_id:
        apply_pos_success(intent, response)
    elif is_pos_terminal_failure(response):
        apply_pos_terminal_failure(intent, response)
    return response


@frappe.whitelist()
def expire_stale_unpaid_intents(limit=500, dry_run=0):
    require_sync_role()
    return _expire_stale_unpaid_intents(limit=limit, dry_run=dry_run)


def _expire_stale_unpaid_intents(limit=500, dry_run=0):
    settings = get_settings()
    now = now_datetime()
    expired = []

    rows = frappe.get_all(
        'Payment Intent',
        filters={
            'status': ['in', ['Draft', 'Requested']],
            'amount_paid': ['<=', 0],
        },
        fields=[
            'name',
            'status',
            'gateway',
            'payment_mode',
            'payment_status',
            'pos_request_status',
            'amount_paid',
            'expires_on',
            'requested_on',
            'creation',
            'reference_doctype',
            'reference_name',
            'sales_invoice',
        ],
        limit=cint(limit) or 500,
        order_by='creation asc',
    )

    for row in rows:
        expiry, reason = get_unpaid_intent_expiry(row, settings)
        if not expiry or expiry > now:
            continue

        expired.append({'payment_intent': row.name, 'expired_on': expiry, 'reason': reason})
        if cint(dry_run):
            continue
        mark_unpaid_intent_expired(row, reason)

    return {'expired': expired, 'count': len(expired), 'dry_run': cint(dry_run)}


def get_unpaid_intent_expiry(row, settings):
    if flt(row.amount_paid or 0) > 0:
        return None, None

    if row.payment_mode == 'POS':
        base = row.requested_on or row.creation
        if not base:
            return None, None
        auto_cancel_minutes = cint(getattr(settings, 'pinelabs_auto_cancel_duration', 0) or 5)
        grace_minutes = 1
        return (
            add_to_date(base, minutes=auto_cancel_minutes + grace_minutes),
            f'POS request expired after {auto_cancel_minutes + grace_minutes} minutes without successful payment',
        )

    if row.expires_on:
        return row.expires_on, 'Payment request expired without successful payment'

    fallback_hours = cint(getattr(settings, 'payment_link_expiry_hours', 0) or 72)
    return (
        add_to_date(row.requested_on or row.creation, hours=fallback_hours),
        f'Payment request expired after {fallback_hours} hours without successful payment',
    )


def mark_unpaid_intent_expired(row, reason):
    try:
        frappe.flags.payment_orchestrator_system_update = True
        updates = {
            'status': 'Expired',
            'payment_status': 'expired',
            'amount_paid': 0,
            'amount_allocated': 0,
            'amount_unallocated': 0,
            'allocation_status': 'Unallocated',
            'last_synced_on': now_datetime(),
        }
        if row.payment_mode == 'POS':
            updates['pos_request_status'] = reason
            updates['pos_failure_reason'] = reason
        elif row.payment_mode == 'QR Code':
            updates['qr_status'] = 'expired'

        frappe.db.set_value('Payment Intent', row.name, updates, update_modified=False)
        update_reference_payment_summary(row.reference_doctype, row.reference_name)
        if row.sales_invoice:
            update_reference_payment_summary('Sales Invoice', row.sales_invoice)
    finally:
        frappe.flags.payment_orchestrator_system_update = False


def require_sync_role():
    if frappe.session.user == 'Administrator':
        return
    roles = set(frappe.get_roles(frappe.session.user))
    if not roles.intersection({'Accounts Manager', 'Accounts User', 'System Manager'}):
        frappe.throw('Not permitted to sync Payment Intents', frappe.PermissionError)
