import frappe

from payment_orchestrator.services import update_reference_payment_summary


@frappe.whitelist()
def get_reference_dashboard(reference_doctype, reference_name):
    summary = update_reference_payment_summary(reference_doctype, reference_name)
    intents = frappe.get_all(
        'Payment Intent',
        filters={'reference_doctype': reference_doctype, 'reference_name': reference_name},
        fields=['name', 'status', 'gateway', 'payment_mode', 'request_type', 'amount_requested', 'amount_paid', 'amount_allocated', 'amount_unallocated', 'payment_link_url', 'qr_code_url', 'provider_payment_id', 'modified'],
        order_by='modified desc',
        limit=20,
    )
    return {
        'summary': summary,
        'intents': intents,
    }
