import frappe

from razorpay_integration.logic import allocate_available_amount, refresh_intent_and_reference


@frappe.whitelist()
def auto_allocate(payment_intent):
    intent = frappe.get_doc('Payment Intent', payment_intent)
    payment_entry = _resolve_payment_entry(intent)
    if not payment_entry:
        frappe.throw('No Payment Entry linked to this payment intent yet')
    allocated = allocate_available_amount(intent, payment_entry)
    refresh_intent_and_reference(intent)
    return {
        'payment_intent': intent.name,
        'allocated_amount': allocated,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


@frappe.whitelist()
def sync_reference_summary(reference_doctype=None, reference_name=None, doc=None, method=None):
    from razorpay_integration.services import update_reference_payment_summary

    if doc is not None:
        reference_doctype = doc.doctype
        reference_name = doc.name
    if not reference_doctype or not reference_name:
        return None
    return update_reference_payment_summary(reference_doctype, reference_name)


def _resolve_payment_entry(intent):
    return frappe.db.get_value('Payment Entry', {'reference_no': ['in', [intent.provider_payment_id, intent.name]]}, 'name')
