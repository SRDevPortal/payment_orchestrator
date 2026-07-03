import frappe

from payment_orchestrator.api.common.validation import ensure_reference_read_permission


@frappe.whitelist()
def get_payment_intent(payment_intent):
    doc = frappe.get_doc("Payment Intent", payment_intent)
    ensure_reference_read_permission(doc.reference_doctype, doc.reference_name)
    return doc.as_dict()
