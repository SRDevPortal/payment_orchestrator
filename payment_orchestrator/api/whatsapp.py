import frappe

from payment_orchestrator.api.common.validation import ensure_payment_intent_action_permission
from payment_orchestrator.notifications.whatsapp import send_payment_whatsapp_message


@frappe.whitelist()
def send_payment_request(payment_intent, mobile_no=None):
    intent = frappe.get_doc("Payment Intent", payment_intent)
    ensure_payment_intent_action_permission(intent)
    return send_payment_whatsapp_message(intent, mobile_no=mobile_no)

