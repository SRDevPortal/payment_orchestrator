import frappe

from payment_orchestrator.api.common.validation import (
    ensure_payment_intent_action_permission,
    ensure_reference_read_permission,
)
from payment_orchestrator.notifications.whatsapp import sync_payment_whatsapp_delivery_status


@frappe.whitelist()
def get_payment_intent(payment_intent):
    doc = frappe.get_doc("Payment Intent", payment_intent)
    ensure_reference_read_permission(doc.reference_doctype, doc.reference_name)
    sync_payment_whatsapp_delivery_status(doc)
    doc.reload()
    return doc.as_dict()


@frappe.whitelist()
def mark_payment_intent_shared(payment_intent, sent_via):
    doc = frappe.get_doc("Payment Intent", payment_intent)
    ensure_payment_intent_action_permission(doc)

    sent_via = (sent_via or "").strip()
    if sent_via not in {"WhatsApp", "SMS", "Email", "Manual Copy", "Other"}:
        frappe.throw("Invalid payment share channel")

    frappe.db.set_value("Payment Intent", doc.name, "sent_via", sent_via, update_modified=False)
    return {"ok": True, "payment_intent": doc.name, "sent_via": sent_via}
