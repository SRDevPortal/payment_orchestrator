import frappe
from frappe.utils import cint, now_datetime

from razorpay_integration.logic import allocate_available_amount, refresh_intent_and_reference
from razorpay_integration.provider.razorpay.client import RazorpayClient
from razorpay_integration.utils import get_settings


def run_periodic_sync():
    settings = get_settings()
    if cint(settings.enable_settlement_sync):
        # placeholder for settlement sync extension
        pass

    stale_intents = frappe.get_all(
        'Payment Intent',
        filters={'status': ['in', ['Requested', 'Paid', 'Partially Allocated']]},
        fields=['name', 'provider_link_id', 'provider_payment_id'],
        limit=100,
    )

    client = RazorpayClient(settings=settings)
    for row in stale_intents:
        try:
            intent = frappe.get_doc('Payment Intent', row.name)
            if row.provider_link_id:
                data = client.fetch_payment_link(row.provider_link_id)
                intent.db_set('payment_status', data.get('status'))
                intent.db_set('last_synced_on', now_datetime())
            payment_entry = frappe.db.get_value('Payment Entry', {'reference_no': ['in', [intent.provider_payment_id, intent.name]]}, 'name')
            if payment_entry and cint(settings.enable_auto_allocation):
                allocate_available_amount(intent, payment_entry)
                refresh_intent_and_reference(intent)
        except Exception:
            frappe.log_error(frappe.get_traceback(), f'Razorpay sync failed for {row.name}')
