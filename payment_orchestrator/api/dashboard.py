import frappe

from payment_orchestrator.api.common.validation import ensure_reference_read_permission
from payment_orchestrator.services import update_reference_payment_summary
from payment_orchestrator.utils import get_settings, is_doctype_enabled


@frappe.whitelist()
def get_reference_dashboard(reference_doctype, reference_name):
    if not is_doctype_enabled(reference_doctype):
        frappe.throw(f'Payment Orchestrator is disabled for {reference_doctype}')

    if not reference_name or str(reference_name).startswith("new-") or not frappe.db.exists(reference_doctype, reference_name):
        return {
            'summary': empty_summary(),
            'intents': [],
        }

    ensure_reference_read_permission(reference_doctype, reference_name)
    summary = update_reference_payment_summary(reference_doctype, reference_name)
    query_args = {
        'fields': ['name', 'status', 'gateway', 'payment_mode', 'request_type', 'amount_requested', 'amount_paid', 'amount_allocated', 'amount_unallocated', 'currency', 'payment_link_url', 'qr_code_url', 'provider_payment_id', 'modified'],
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
        'summary': with_currency(summary, intents),
        'intents': intents,
    }


def empty_summary():
    return with_currency({
        'total_requested': 0,
        'total_paid': 0,
        'total_allocated': 0,
        'total_unallocated': 0,
        'last_payment_intent': None,
    })


def with_currency(summary, intents=None):
    summary = dict(summary or {})
    currency = None
    for intent in intents or []:
        currency = intent.get('currency')
        if currency:
            break
    summary['currency'] = currency or getattr(get_settings(), 'default_currency', None) or 'INR'
    return summary
