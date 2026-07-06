import frappe

from payment_orchestrator.api.common.validation import ensure_reference_read_permission
from payment_orchestrator.services import update_reference_payment_summary
from payment_orchestrator.utils import is_doctype_enabled


@frappe.whitelist()
def get_reference_dashboard(reference_doctype, reference_name):
    if not is_doctype_enabled(reference_doctype):
        frappe.throw(f'Payment Orchestrator is disabled for {reference_doctype}')

    ensure_reference_read_permission(reference_doctype, reference_name)
    summary = update_reference_payment_summary(reference_doctype, reference_name)
    query_args = {
        'fields': ['name', 'status', 'gateway', 'payment_mode', 'request_type', 'amount_requested', 'amount_paid', 'amount_allocated', 'amount_unallocated', 'payment_link_url', 'qr_code_url', 'provider_payment_id', 'modified'],
        'order_by': 'modified desc',
        'limit': 20,
    }
    if reference_doctype == 'Sales Invoice':
        query_args['or_filters'] = [
            {'reference_doctype': reference_doctype, 'reference_name': reference_name},
            {'sales_invoice': reference_name},
        ]
    else:
        query_args['filters'] = {'reference_doctype': reference_doctype, 'reference_name': reference_name}
    intents = frappe.get_all('Payment Intent', **query_args)
    return {
        'summary': summary,
        'intents': intents,
    }
