import frappe

from payment_orchestrator.api.common.validation import ensure_reference_read_permission
from payment_orchestrator.notifications.whatsapp import sync_payment_whatsapp_delivery_status


@frappe.whitelist()
def get_payment_intent(payment_intent):
    doc = frappe.get_doc("Payment Intent", payment_intent)
    ensure_reference_read_permission(doc.reference_doctype, doc.reference_name)
    sync_payment_whatsapp_delivery_status(doc)
    doc.reload()
    return doc.as_dict()
