import frappe
from frappe.utils import cint, now_datetime

from payment_orchestrator.api.provider import fetch_payment_link
from payment_orchestrator.logic import (
    allocate_available_amount,
    apply_unpaid_terminal_provider_status,
    refresh_intent_and_reference,
)
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
                fetch_payment_link(intent.name)
                intent.reload()
            if row.provider_qr_id:
                client = RazorpayClient(settings=settings, mode=intent.provider_mode or 'Test')
                data = client.fetch_qr_code(row.provider_qr_id)
                if not apply_unpaid_terminal_provider_status(intent, data.get('status'), data):
                    intent.db_set('qr_status', data.get('status'))
                    intent.db_set('payment_status', data.get('status'))
                    intent.db_set('last_synced_on', now_datetime())
            payment_entry = frappe.db.get_value('Payment Entry', {'reference_no': ['in', [intent.provider_payment_id, intent.name]]}, 'name')
            if payment_entry and cint(settings.enable_auto_allocation):
                allocate_available_amount(intent, payment_entry)
                refresh_intent_and_reference(intent)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f'Razorpay sync failed for {row.name}')
