import frappe
from frappe.utils import cint, flt, getdate, nowdate

from payment_orchestrator.services import (
    build_reference_context,
    get_allocation_targets,
    update_reference_payment_summary,
)
from payment_orchestrator.utils import (
    as_json,
    ensure_mode_of_payment,
    get_settings,
    mode_of_payment_account,
)


def process_provider_payment_success(payload, event_doc=None):
    payment_entity = _extract_payment_entity(payload)
    notes = payment_entity.get('notes', {}) or {}
    payment_intent_name = notes.get('payment_intent')
    if payment_intent_name and not frappe.db.exists('Payment Intent', payment_intent_name):
        payment_intent_name = None
    payment_intent_name = payment_intent_name or _find_intent_by_provider_ids(payment_entity)
    if not payment_intent_name:
        return {
            'ignored': True,
            'reason': 'Unable to resolve a local Payment Intent from webhook payload',
        }

    frappe.db.sql(
        'select name from `tabPayment Intent` where name=%s for update',
        payment_intent_name,
    )
    intent = frappe.get_doc('Payment Intent', payment_intent_name)
    was_fully_paid = is_payment_intent_fully_paid(intent)
    if intent.provider_payment_id and intent.provider_payment_id == payment_entity.get('id'):
        if intent.reference_doctype == 'Patient Encounter':
            sync_encounter_multi_payment_from_intent(intent)
            refresh_intent_and_reference(intent)
            _publish_payment_completion(intent, None, 0)
            return {'payment_intent': intent.name, 'payment_entry': None, 'duplicate': True}
        existing_pe = _existing_payment_entry(intent)
        if existing_pe:
            _publish_payment_completion(intent, existing_pe, 0)
            return {'payment_intent': intent.name, 'payment_entry': existing_pe, 'duplicate': True}

    amount_paid = flt(payment_entity.get('amount') or payment_entity.get('amount_paid') or 0) / 100
    if amount_paid <= 0 and payment_entity.get('status') in ('paid', 'captured'):
        amount_paid = flt(intent.amount_requested or 0)
    settings = get_settings()
    if amount_paid > flt(intent.amount_requested or 0) and not getattr(settings, 'allow_overpayment', 0):
        frappe.throw('Provider payment amount is greater than requested amount')

    intent.db_set('provider_payment_id', payment_entity.get('id'))
    intent.db_set('gateway', intent.gateway or ('Pine Labs' if intent.request_channel == 'POS' else 'Razorpay'))
    intent.db_set('payment_mode', intent.payment_mode or ('POS' if intent.request_channel == 'POS' else 'Payment Link'))
    intent.db_set('provider_event_id', payment_entity.get('id'))
    intent.db_set('provider_pos_request_id', payment_entity.get('pos_request_id') or payment_entity.get('payment_request_id') or intent.provider_pos_request_id)
    intent.db_set('provider_order_id', payment_entity.get('order_id') or intent.provider_order_id)
    intent.db_set('provider_qr_id', payment_entity.get('qr_code_id') or payment_entity.get('qr_code') or intent.provider_qr_id)
    intent.db_set('provider_terminal_id', payment_entity.get('terminal_id') or payment_entity.get('device_id') or intent.provider_terminal_id)
    intent.db_set('payment_status', payment_entity.get('status'))
    if intent.request_channel == 'POS':
        intent.db_set('pos_request_status', payment_entity.get('status') or 'paid')
    intent.db_set('amount_paid', amount_paid)
    intent.db_set('amount_unallocated', amount_paid)
    intent.db_set('paid_on', frappe.utils.now_datetime())
    intent.db_set('provider_payload_snapshot', as_json(payload))

    intent.reload()
    if intent.reference_doctype == 'Patient Encounter':
        sync_encounter_multi_payment_from_intent(intent)
        refresh_intent_and_reference(intent)
        update_encounter_status_after_payment(intent, was_fully_paid=was_fully_paid)
        _publish_payment_completion(intent, None, 0)
        return {
            'payment_intent': intent.name,
            'payment_entry': None,
            'allocated_amount': 0,
            'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
        }

    payment_entry_name = None
    if settings.auto_create_payment_entry_on_success:
        payment_entry_name = create_payment_entry_for_intent(intent)
    allocated_amount = 0
    if settings.enable_auto_allocation and payment_entry_name:
        allocated_amount = allocate_available_amount(intent, payment_entry_name)

    refresh_intent_and_reference(intent)
    _publish_payment_completion(intent, payment_entry_name, allocated_amount)

    return {
        'payment_intent': intent.name,
        'payment_entry': payment_entry_name,
        'allocated_amount': allocated_amount,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


def create_payment_entry_for_intent(intent):
    existing = _existing_payment_entry(intent)
    if existing:
        return existing

    created_by_agent = _session_user()

    def create_entry():
        settings = get_settings()
        context = build_reference_context(intent.reference_doctype, intent.reference_name)
        amount = flt(intent.amount_paid or intent.amount_requested)
        if amount <= 0:
            frappe.throw('Cannot create Payment Entry with zero amount')

        mode_of_payment = _resolve_mode_of_payment(intent, settings)
        paid_to_account = _resolve_paid_to_account(intent, settings, mode_of_payment)
        if not paid_to_account:
            frappe.throw(
                f'Configure a default account for Mode of Payment {mode_of_payment} and company '
                f'{intent.company or settings.company}'
            )
        pe_doc = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Receive',
            'company': intent.company or settings.company,
            'posting_date': nowdate(),
            'party_type': 'Customer',
            'party': _resolve_customer(intent, context),
            'party_name': context.get('party_name'),
            'paid_amount': amount,
            'received_amount': amount,
            'paid_to': paid_to_account,
            'reference_no': intent.provider_payment_id or intent.name,
            'reference_date': nowdate(),
            'remarks': f'Payment collected via {intent.provider} for {intent.reference_doctype} {intent.reference_name}',
            'mode_of_payment': mode_of_payment,
            'reference_doctype': intent.reference_doctype,
            'reference_name': intent.reference_name,
            'created_by_agent': created_by_agent,
        })

        if intent.sales_invoice and intent.request_type == 'Against Invoice':
            pe_doc.append('references', {
                'reference_doctype': 'Sales Invoice',
                'reference_name': intent.sales_invoice,
                'allocated_amount': min(amount, frappe.db.get_value('Sales Invoice', intent.sales_invoice, 'outstanding_amount') or amount),
                'total_amount': frappe.db.get_value('Sales Invoice', intent.sales_invoice, 'grand_total') or amount,
                'outstanding_amount': frappe.db.get_value('Sales Invoice', intent.sales_invoice, 'outstanding_amount') or amount,
            })

        pe_doc.insert(ignore_permissions=True)
        if settings.auto_submit_payment_entry:
            pe_doc.submit()
        return pe_doc.name

    return _run_as_system_user_for_guest(create_entry)


def process_provider_refund(payment_id, refund_id, refund_amount, provider_status='refunded'):
    intent_name = frappe.db.get_value('Payment Intent', {'provider_payment_id': payment_id}, 'name')
    if not intent_name:
        return {'ignored': True, 'event': 'refund', 'reason': 'No local Payment Intent found for refund'}

    frappe.db.sql('select name from `tabPayment Intent` where name=%s for update', intent_name)
    intent = frappe.get_doc('Payment Intent', intent_name)
    processed_refund_ids = frappe.parse_json(getattr(intent, 'provider_refund_ids', None) or '[]')
    if not isinstance(processed_refund_ids, list):
        processed_refund_ids = []
    if refund_id and refund_id in processed_refund_ids:
        return {'duplicate': True, 'payment_intent': intent.name, 'status': intent.status}
    refund_amount = flt(refund_amount)
    if refund_amount <= 0:
        return {'ignored': True, 'event': 'refund', 'reason': 'Refund amount is missing or zero'}

    existing_refund_entry = None
    if refund_id:
        existing_refund_entry = frappe.db.get_value('Payment Entry', {'reference_no': refund_id}, 'name')

    already_refunded = flt(getattr(intent, 'amount_refunded', 0) or 0)
    refundable = max(flt(intent.amount_paid or 0) - already_refunded, 0)
    applied_refund = min(refund_amount, refundable)
    if applied_refund <= 0:
        return {'duplicate': True, 'payment_intent': intent.name, 'status': intent.status}

    refund_entry = existing_refund_entry or create_refund_payment_entry_for_intent(
        intent, applied_refund, refund_id
    )
    if refund_entry and not frappe.db.exists(
        'Payment Allocation', {'payment_intent': intent.name, 'payment_entry': refund_entry}
    ):
        _reverse_allocations_for_refund(intent, refund_entry, applied_refund)

    total_refunded = already_refunded + applied_refund
    fully_refunded = total_refunded + 0.000001 >= flt(intent.amount_paid or 0)
    intent.db_set('amount_refunded', total_refunded)
    intent.db_set('refund_status', 'Fully Refunded' if fully_refunded else 'Partially Refunded')
    intent.db_set('payment_status', provider_status)
    if refund_id:
        processed_refund_ids.append(refund_id)
        intent.db_set('provider_refund_ids', frappe.as_json(processed_refund_ids))
    intent.reload()
    refresh_intent_and_reference(intent)
    return {
        'payment_intent': intent.name,
        'payment_entry': refund_entry,
        'refunded_amount': applied_refund,
        'total_refunded': total_refunded,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


def create_refund_payment_entry_for_intent(intent, amount, refund_id=None):
    original_name = getattr(intent, 'payment_entry', None) or _existing_payment_entry(intent)
    if not original_name:
        return None

    original = frappe.get_doc('Payment Entry', original_name)
    if not original.paid_from or not original.paid_to:
        frappe.throw(f'Original Payment Entry {original.name} is missing accounting accounts')

    def create_entry():
        refund = frappe.get_doc({
            'doctype': 'Payment Entry',
            'payment_type': 'Pay',
            'company': original.company,
            'posting_date': nowdate(),
            'party_type': original.party_type,
            'party': original.party,
            'party_name': original.party_name,
            'paid_from': original.paid_to,
            'paid_to': original.paid_from,
            'paid_amount': amount,
            'received_amount': amount,
            'reference_no': refund_id or f'refund-{intent.name}',
            'reference_date': nowdate(),
            'remarks': f'Refund for Payment Intent {intent.name} and Payment Entry {original.name}',
            'mode_of_payment': original.mode_of_payment,
        })
        refund.insert(ignore_permissions=True)
        if original.docstatus == 1:
            refund.submit()
        return refund.name

    return _run_as_system_user_for_guest(create_entry)


def _publish_payment_completion(intent, payment_entry_name=None, allocated_amount=0):
    try:
        frappe.publish_realtime(
            'payment_orchestrator_payment_completed',
            {
                'payment_intent': intent.name,
                'payment_entry': payment_entry_name,
                'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
                'amount_paid': flt(intent.amount_paid or 0),
                'allocated_amount': allocated_amount,
            },
            user=intent.requested_by,
            after_commit=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f'Payment completion realtime failed for {intent.name}')


def allocate_available_amount(intent, payment_entry_name):
    intent.reload()
    remaining = flt(intent.amount_paid) - flt(intent.amount_allocated)
    if remaining <= 0:
        return 0

    allocated_total = 0
    for target in sorted(get_allocation_targets(intent), key=lambda x: x.get('priority', 99)):
        if remaining <= 0:
            break
        if target['doctype'] != 'Sales Invoice':
            continue
        outstanding = flt(frappe.db.get_value('Sales Invoice', target['name'], 'outstanding_amount') or 0)
        if outstanding <= 0:
            continue
        alloc = min(remaining, outstanding)
        if _allocation_exists(intent.name, target['doctype'], target['name']):
            continue
        allocation = frappe.get_doc({
            'doctype': 'Payment Allocation',
            'payment_intent': intent.name,
            'payment_entry': payment_entry_name,
            'allocated_amount': alloc,
            'target_doctype': target['doctype'],
            'target_name': target['name'],
            'allocation_date': frappe.utils.now_datetime(),
            'remarks': 'Auto allocation by Razorpay',
        })
        allocation.insert(ignore_permissions=True)
        remaining -= alloc
        allocated_total += alloc

    return allocated_total


def refresh_intent_and_reference(intent):
    allocated_total = flt(frappe.db.sql(
        "select coalesce(sum(allocated_amount),0) from `tabPayment Allocation` where payment_intent=%s and status!='Reversed'",
        intent.name,
    )[0][0])
    amount_paid = flt(intent.amount_paid or 0)
    amount_refunded = flt(getattr(intent, 'amount_refunded', 0) or 0)
    net_paid = max(amount_paid - amount_refunded, 0)
    unallocated = max(net_paid - allocated_total, 0)

    current_status = frappe.db.get_value('Payment Intent', intent.name, 'status') or intent.status
    status = 'Paid'
    allocation_status = 'Unallocated'
    if amount_paid > 0 and amount_refunded + 0.000001 >= amount_paid:
        status = 'Refunded'
        allocation_status = 'Unallocated'
    elif amount_refunded > 0:
        status = 'Partially Refunded'
        allocation_status = 'Partially Allocated' if allocated_total > 0 else 'Unallocated'
    elif amount_paid <= 0:
        status = current_status if current_status in {'Expired', 'Cancelled'} else 'Requested'
    elif allocated_total > 0 and unallocated <= 0:
        status = 'Allocated'
        allocation_status = 'Fully Allocated'
    elif allocated_total > 0 and unallocated > 0:
        status = 'Partially Allocated'
        allocation_status = 'Partially Allocated'
    elif amount_paid > 0:
        allocation_status = 'Unallocated'

    intent.db_set('amount_allocated', allocated_total)
    intent.db_set('amount_unallocated', unallocated)
    intent.db_set('status', status)
    intent.db_set('allocation_status', allocation_status)
    update_reference_payment_summary(intent.reference_doctype, intent.reference_name)


def _reverse_allocations_for_refund(intent, refund_payment_entry, refund_amount):
    rows = frappe.db.sql(
        """
        select target_doctype, target_name, sum(allocated_amount) as allocated_amount
        from `tabPayment Allocation`
        where payment_intent=%s and status!='Reversed'
        group by target_doctype, target_name
        having sum(allocated_amount) > 0
        order by min(allocation_date) desc
        """,
        intent.name,
        as_dict=True,
    )
    remaining = flt(refund_amount)
    for row in rows:
        if remaining <= 0:
            break
        reversed_amount = min(remaining, flt(row.allocated_amount))
        frappe.get_doc({
            'doctype': 'Payment Allocation',
            'status': 'Allocated',
            'payment_intent': intent.name,
            'payment_entry': refund_payment_entry,
            'allocated_amount': -reversed_amount,
            'target_doctype': row.target_doctype,
            'target_name': row.target_name,
            'allocation_date': frappe.utils.now_datetime(),
            'remarks': 'Allocation reversal for provider refund',
        }).insert(ignore_permissions=True)
        remaining -= reversed_amount


def is_payment_intent_fully_paid(intent):
    amount_requested = flt(getattr(intent, 'amount_requested', 0) or 0)
    amount_paid = flt(getattr(intent, 'amount_paid', 0) or 0)
    return amount_requested > 0 and amount_paid + 0.000001 >= amount_requested


def update_encounter_status_after_payment(intent, was_fully_paid=False):
    if was_fully_paid or intent.reference_doctype != 'Patient Encounter' or not intent.reference_name:
        return None
    if not is_payment_intent_fully_paid(intent):
        return None

    settings = get_settings()
    target_status = (getattr(settings, 'encounter_status_after_payment', None) or '').strip()
    if not target_status:
        return None
    if not frappe.db.exists('Patient Encounter', intent.reference_name):
        return None

    encounter_meta = frappe.get_meta('Patient Encounter')
    if not encounter_meta.has_field('sr_encounter_status'):
        return None
    if not frappe.db.exists('DocType', 'SR Encounter Status') or not frappe.db.exists('SR Encounter Status', target_status):
        frappe.log_error(
            f'Configured SR Encounter Status {target_status} does not exist',
            'Payment Orchestrator encounter status update skipped',
        )
        return None
    status_meta = frappe.get_meta('SR Encounter Status')
    if status_meta.has_field('is_active') and not cint(
        frappe.db.get_value('SR Encounter Status', target_status, 'is_active')
    ):
        frappe.log_error(
            f'Configured SR Encounter Status {target_status} is inactive',
            'Payment Orchestrator encounter status update skipped',
        )
        return None

    current_status = frappe.db.get_value('Patient Encounter', intent.reference_name, 'sr_encounter_status') or ''
    if current_status == target_status:
        return target_status
    status_at_request = (getattr(intent, 'encounter_status_at_request', None) or '').strip()
    if status_at_request and current_status != status_at_request:
        return None

    frappe.db.set_value('Patient Encounter', intent.reference_name, 'sr_encounter_status', target_status)
    try:
        encounter = frappe.get_doc('Patient Encounter', intent.reference_name)
        encounter.add_comment(
            'Info',
            f'Encounter Status automatically changed to {target_status} after successful payment '
            f'{intent.provider_payment_id or intent.name} (Payment Intent {intent.name}).',
        )
    except Exception:
        frappe.log_error(
            frappe.get_traceback(),
            f'Payment Orchestrator encounter status comment failed for {intent.reference_name}',
        )
    return target_status


def apply_unpaid_terminal_provider_status(intent, provider_status=None, provider_payload=None):
    if flt(getattr(intent, 'amount_paid', 0) or 0) > 0:
        return None

    status = (provider_status or '').strip().lower()
    mapped_status = None
    if status in {'closed', 'expired'}:
        mapped_status = 'Expired'
    elif status in {'cancelled', 'canceled', 'failed'}:
        mapped_status = 'Cancelled'

    if not mapped_status:
        return None

    updates = {
        'status': mapped_status,
        'payment_status': provider_status,
        'amount_paid': 0,
        'amount_allocated': 0,
        'amount_unallocated': 0,
        'allocation_status': 'Unallocated',
        'last_synced_on': frappe.utils.now_datetime(),
    }
    if provider_payload is not None:
        updates['provider_payload_snapshot'] = as_json(provider_payload)
    if getattr(intent, 'payment_mode', None) == 'QR Code':
        updates['qr_status'] = provider_status

    frappe.db.set_value('Payment Intent', intent.name, updates, update_modified=False)
    update_reference_payment_summary(intent.reference_doctype, intent.reference_name)
    if getattr(intent, 'sales_invoice', None):
        update_reference_payment_summary('Sales Invoice', intent.sales_invoice)
    return mapped_status


def sync_encounter_multi_payment_from_intent(intent):
    if intent.reference_doctype != 'Patient Encounter' or not intent.reference_name:
        return None
    if not frappe.db.exists('Patient Encounter', intent.reference_name):
        return None

    encounter = frappe.get_doc('Patient Encounter', intent.reference_name)
    if not frappe.get_meta('Patient Encounter').get_field('enc_multi_payments'):
        return None

    row = _find_encounter_payment_row(encounter, intent)
    paid_on = getdate(intent.paid_on) if intent.paid_on else nowdate()
    reference_no = _provider_reference_no(intent)
    provider_confirmation_url = _provider_confirmation_url(intent)
    values = {
        'mmp_paid_amount': flt(intent.amount_paid or intent.amount_requested),
        'mmp_mode_of_payment': _resolve_mode_of_payment(intent, get_settings()),
        'mmp_reference_no': reference_no,
        'mmp_reference_date': paid_on,
        'mmp_payment_intent': intent.name,
        'mmp_provider_payment_id': intent.provider_payment_id or reference_no,
        'mmp_gateway': intent.gateway,
        'mmp_payment_mode': intent.payment_mode,
        'mmp_orchestrator_status': 'Paid',
    }
    if provider_confirmation_url and not getattr(row, 'mmp_payment_proof', None):
        values['mmp_payment_proof'] = provider_confirmation_url
    values = _filter_values_for_doctype('SR Multi Mode Payment', values)

    if row is not None:
        frappe.db.set_value('SR Multi Mode Payment', row.name, values, update_modified=False)
        return row.name

    next_idx = max([flt(getattr(item, 'idx', 0)) for item in getattr(encounter, 'enc_multi_payments', []) or []] or [0]) + 1
    row = frappe.get_doc({
        'doctype': 'SR Multi Mode Payment',
        'parent': encounter.name,
        'parenttype': 'Patient Encounter',
        'parentfield': 'enc_multi_payments',
        'idx': next_idx,
        **values,
    })
    row.insert(ignore_permissions=True)
    frappe.db.set_value('Patient Encounter', encounter.name, 'modified', frappe.utils.now(), update_modified=False)
    return row.name


def link_encounter_billing_result(payment_intent, sales_invoice=None, payment_entry=None, allocated_amount=0):
    if not payment_intent or not frappe.db.exists('Payment Intent', payment_intent):
        return None

    intent = frappe.get_doc('Payment Intent', payment_intent)
    updates = {}
    meta = frappe.get_meta('Payment Intent')
    if sales_invoice and meta.get_field('sales_invoice'):
        updates['sales_invoice'] = sales_invoice
    if payment_entry and meta.get_field('payment_entry'):
        updates['payment_entry'] = payment_entry
    if updates:
        frappe.db.set_value('Payment Intent', intent.name, updates, update_modified=False)

    alloc_amount = flt(allocated_amount or intent.amount_paid or 0)
    if sales_invoice and payment_entry and alloc_amount > 0:
        _upsert_payment_allocation(intent.name, payment_entry, sales_invoice, alloc_amount)

    intent.reload()
    refresh_intent_and_reference(intent)
    if sales_invoice:
        update_reference_payment_summary('Sales Invoice', sales_invoice)
    return {
        'payment_intent': intent.name,
        'sales_invoice': sales_invoice,
        'payment_entry': payment_entry,
        'allocated_amount': alloc_amount,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


def _existing_payment_entry(intent):
    keys = [k for k in [intent.provider_payment_id, intent.name] if k]
    if not keys:
        return None
    return frappe.db.get_value('Payment Entry', {'reference_no': ['in', keys]}, 'name')


def _resolve_customer(intent, context):
    settings = get_settings()
    if intent.reference_doctype in ('Sales Invoice', 'Sales Order') and context.get('party'):
        return context.get('party')
    if intent.reference_doctype == 'Patient Encounter':
        patient = intent.patient or context.get('patient')
        patient_name = context.get('party_name')
        if patient and frappe.db.exists('Customer', patient):
            return patient
        if patient_name:
            existing = frappe.db.get_value('Customer', {'customer_name': patient_name}, 'name')
            if existing:
                return existing
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': patient_name or patient or intent.reference_name,
            'customer_group': frappe.db.get_value('Customer Group', {}, 'name') or 'All Customer Groups',
            'territory': frappe.db.get_value('Territory', {}, 'name') or 'All Territories',
        })
        customer.insert(ignore_permissions=True)
        return customer.name
    if intent.reference_doctype == 'CRM Lead' and getattr(settings, 'crm_lead_auto_create_customer', 1):
        lead_name = context.get('party_name') or intent.reference_name
        existing = frappe.db.get_value('Customer', {'customer_name': lead_name}, 'name')
        if existing:
            return existing
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': lead_name,
            'customer_group': frappe.db.get_value('Customer Group', {}, 'name') or 'All Customer Groups',
            'territory': frappe.db.get_value('Territory', {}, 'name') or 'All Territories',
        })
        customer.insert(ignore_permissions=True)
        return customer.name
    return context.get('party') or context.get('party_name')


def _resolve_paid_to_account(intent, settings, mode_of_payment=None):
    company = intent.company or settings.company
    account = mode_of_payment_account(
        company,
        mode_of_payment or _resolve_mode_of_payment(intent, settings),
    )
    if account:
        return account
    return frappe.get_value('Company', company, 'default_bank_account') or frappe.get_value('Company', company, 'default_cash_account')


def _resolve_mode_of_payment(intent, settings):
    if intent.request_channel == 'POS' or intent.payment_mode == 'POS':
        if intent.gateway == 'Razorpay':
            mode = 'Razorpay POS'
        else:
            mode = settings.pos_mode_of_payment or 'Pine Labs POS'
    elif intent.gateway == 'Pine Labs':
        mode = 'Pine Labs'
    else:
        mode = settings.default_mode_of_payment or 'Razorpay'
    return ensure_mode_of_payment(mode)


def _session_user():
    return getattr(frappe.session, 'user', None) or 'Administrator'


def _run_as_system_user_for_guest(callback):
    original_user = _session_user()
    if original_user != 'Guest':
        return callback()

    frappe.set_user('Administrator')
    try:
        return callback()
    finally:
        frappe.set_user(original_user)


def _allocation_exists(payment_intent, target_doctype, target_name):
    return frappe.db.exists('Payment Allocation', {
        'payment_intent': payment_intent,
        'target_doctype': target_doctype,
        'target_name': target_name,
        'status': ['!=', 'Reversed'],
    })


def _find_encounter_payment_row(encounter, intent):
    reference_no = _provider_reference_no(intent)
    for row in getattr(encounter, 'enc_multi_payments', []) or []:
        if getattr(row, 'mmp_payment_intent', None) == intent.name:
            return row
        if intent.provider_payment_id and getattr(row, 'mmp_provider_payment_id', None) == intent.provider_payment_id:
            return row
        if reference_no and getattr(row, 'mmp_reference_no', None) == reference_no:
            return row
    return None


def _provider_reference_no(intent):
    return (
        intent.provider_payment_id
        or intent.provider_order_id
        or intent.provider_pos_request_id
        or intent.provider_qr_id
        or intent.provider_link_id
        or intent.name
    )


def _provider_confirmation_url(intent):
    return (
        intent.payment_link_url
        or intent.qr_code_url
        or _provider_confirmation_url_from_payload(getattr(intent, 'provider_payload_snapshot', None))
    )


def _provider_confirmation_url_from_payload(payload):
    if not payload:
        return None
    try:
        data = frappe.parse_json(payload) if isinstance(payload, str) else payload
    except Exception:
        return None
    if not isinstance(data, dict):
        return None

    sources = [
        data,
        data.get('payload', {}).get('payment_link', {}).get('entity', {}),
        data.get('payment_link', {}),
        data.get('data', {}),
    ]
    for source in sources:
        if not isinstance(source, dict):
            continue
        for fieldname in ('short_url', 'long_url', 'payment_link_url', 'payment_link', 'qr_code_url', 'image_url'):
            value = source.get(fieldname)
            if value:
                return value
    return None


def _set_child_values_if_present(row, child_doctype, values):
    meta = frappe.get_meta(child_doctype)
    for fieldname, value in values.items():
        if meta.get_field(fieldname):
            setattr(row, fieldname, value)


def _filter_values_for_doctype(doctype, values):
    meta = frappe.get_meta(doctype)
    return {
        fieldname: value
        for fieldname, value in values.items()
        if meta.get_field(fieldname)
    }


def _upsert_payment_allocation(payment_intent, payment_entry, sales_invoice, allocated_amount):
    existing = frappe.db.get_value('Payment Allocation', {
        'payment_intent': payment_intent,
        'target_doctype': 'Sales Invoice',
        'target_name': sales_invoice,
        'status': ['!=', 'Reversed'],
    }, 'name')
    values = {
        'payment_entry': payment_entry,
        'allocated_amount': allocated_amount,
        'status': 'Allocated',
        'allocation_date': frappe.utils.now_datetime(),
        'remarks': 'Linked from Patient Encounter billing',
    }
    if existing:
        frappe.db.set_value('Payment Allocation', existing, values, update_modified=False)
        return existing

    allocation = frappe.get_doc({
        'doctype': 'Payment Allocation',
        'status': 'Allocated',
        'payment_intent': payment_intent,
        'payment_entry': payment_entry,
        'allocated_amount': allocated_amount,
        'target_doctype': 'Sales Invoice',
        'target_name': sales_invoice,
        'allocation_date': frappe.utils.now_datetime(),
        'remarks': 'Linked from Patient Encounter billing',
    })
    allocation.insert(ignore_permissions=True)
    return allocation.name


def _extract_payment_entity(payload):
    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity')
    if payment_entity:
        qr_code_entity = payload.get('payload', {}).get('qr_code', {}).get('entity')
        if qr_code_entity:
            payment_entity = dict(payment_entity)
            if qr_code_entity.get('id') and not payment_entity.get('qr_code_id'):
                payment_entity['qr_code_id'] = qr_code_entity.get('id')
            if qr_code_entity.get('notes') and not (payment_entity.get('notes') or {}).get('payment_intent'):
                payment_entity['notes'] = qr_code_entity.get('notes')
        return payment_entity
    payment_entity = payload.get('payload', {}).get('pos_payment', {}).get('entity')
    if payment_entity:
        return payment_entity
    payment_entity = payload.get('payload', {}).get('payment_request', {}).get('entity', {}).get('payment')
    if payment_entity:
        return payment_entity
    payment_entity = payload.get('payload', {}).get('payment_request', {}).get('entity')
    if payment_entity:
        return payment_entity
    payment_link_entity = payload.get('payload', {}).get('payment_link', {}).get('entity', {})
    nested = payment_link_entity.get('payments') or []
    if nested:
        payment = dict(nested[0])
        return _merge_payment_link_context(payment, payment_link_entity)
    if payment_link_entity:
        return _payment_entity_from_payment_link(payment_link_entity)
    return {}


def _merge_payment_link_context(payment, payment_link_entity):
    if payment_link_entity.get('id') and not payment.get('payment_link_id'):
        payment['payment_link_id'] = payment_link_entity.get('id')
    if payment_link_entity.get('notes') and not payment.get('notes'):
        payment['notes'] = payment_link_entity.get('notes')
    if not payment.get('amount') and payment_link_entity.get('amount_paid'):
        payment['amount'] = payment_link_entity.get('amount_paid')
    if not payment.get('amount') and payment_link_entity.get('amount'):
        payment['amount'] = payment_link_entity.get('amount')
    return payment


def _payment_entity_from_payment_link(payment_link_entity):
    payment_id = (
        payment_link_entity.get('payment_id')
        or payment_link_entity.get('razorpay_payment_id')
        or payment_link_entity.get('id')
    )
    return {
        'id': payment_id,
        'payment_link_id': payment_link_entity.get('id'),
        'order_id': payment_link_entity.get('order_id'),
        'amount': payment_link_entity.get('amount_paid') or payment_link_entity.get('amount') or 0,
        'status': payment_link_entity.get('status'),
        'notes': payment_link_entity.get('notes') or {},
    }


def _find_intent_by_provider_ids(payment_entity):
    notes = payment_entity.get('notes', {}) or {}
    if notes.get('payment_intent') and frappe.db.exists('Payment Intent', notes.get('payment_intent')):
        return notes.get('payment_intent')
    payment_link_id = payment_entity.get('payment_link_id')
    if not payment_link_id and str(payment_entity.get('id') or '').startswith('plink_'):
        payment_link_id = payment_entity.get('id')
    if payment_link_id:
        return frappe.db.get_value('Payment Intent', {'provider_link_id': payment_link_id}, 'name')
    qr_code_id = payment_entity.get('qr_code_id') or payment_entity.get('qr_code')
    if not qr_code_id and str(payment_entity.get('id') or '').startswith('qr_'):
        qr_code_id = payment_entity.get('id')
    if qr_code_id:
        return frappe.db.get_value('Payment Intent', {'provider_qr_id': qr_code_id}, 'name')
    pos_request_id = payment_entity.get('pos_request_id') or payment_entity.get('payment_request_id')
    if pos_request_id:
        return frappe.db.get_value('Payment Intent', {'provider_pos_request_id': pos_request_id}, 'name')
    order_id = payment_entity.get('order_id')
    if order_id:
        return frappe.db.get_value('Payment Intent', {'provider_order_id': order_id}, 'name')
    return None
