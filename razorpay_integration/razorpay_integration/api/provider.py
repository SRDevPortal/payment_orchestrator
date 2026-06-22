import frappe

from razorpay_integration.provider.razorpay.client import RazorpayClient
from razorpay_integration.utils import get_settings


@frappe.whitelist()
def fetch_payment_link(payment_intent):
    intent = frappe.get_doc('Payment Intent', payment_intent)
    if not intent.provider_link_id:
        frappe.throw('Payment Intent has no provider link id')
    client = RazorpayClient(settings=get_settings())
    data = client.fetch_payment_link(intent.provider_link_id)
    intent.db_set('payment_status', data.get('status'))
    intent.db_set('provider_payload_snapshot', frappe.as_json(data))
    return data


@frappe.whitelist()
def refund_payment(payment_intent, amount=None, notes=None):
    settings = get_settings()
    if not settings.enable_refunds:
        frappe.throw('Refunds are disabled in settings')
    intent = frappe.get_doc('Payment Intent', payment_intent)
    if not intent.provider_payment_id:
        frappe.throw('Payment has not been captured for this intent yet')
    payload = {}
    if amount:
        payload['amount'] = int(round(frappe.utils.flt(amount) * 100))
    if notes:
        payload['notes'] = {'reason': notes}
    client = RazorpayClient(settings=settings)
    response = client.create_refund(intent.provider_payment_id, payload)
    intent.db_set('payment_status', 'refund_initiated')
    return response
