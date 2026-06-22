import frappe

from razorpay_integration.provider.razorpay.client import RazorpayClient
from razorpay_integration.services import create_payment_intent_doc
from razorpay_integration.utils import as_json, get_settings


@frappe.whitelist()
def create_payment_intent(reference_doctype, reference_name, amount, request_type=None, request_channel=None, notes=None):
    amount = frappe.utils.flt(amount)
    if amount <= 0:
        frappe.throw('Amount must be greater than zero')

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel=request_channel,
        notes=notes,
    )

    settings = get_settings()
    client = RazorpayClient(settings=settings)

    payload = {
        'amount': int(round(amount * 100)),
        'currency': intent.currency,
        'accept_partial': 1 if _allow_partial(settings, reference_doctype) else 0,
        'expire_by': int(intent.expires_on.timestamp()) if intent.expires_on else None,
        'reference_id': intent.name,
        'description': f'{reference_doctype} {reference_name} - {intent.request_type}',
        'customer': {
            'name': context.get('party_name') or reference_name,
            'contact': context.get('mobile') or '',
            'email': context.get('email') or '',
        },
        'notify': {
            'sms': False,
            'email': False,
        },
        'notes': {
            'payment_intent': intent.name,
            'reference_doctype': reference_doctype,
            'reference_name': reference_name,
            'request_type': intent.request_type,
            'party': context.get('party') or '',
        },
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    response = client.create_payment_link(payload)

    intent.db_set('provider_payload_snapshot', as_json(response))
    intent.db_set('provider_link_id', response.get('id'))
    intent.db_set('provider_request_id', response.get('reference_id') or intent.name)
    intent.db_set('payment_link_url', response.get('short_url') or response.get('long_url'))
    intent.db_set('payment_status', response.get('status'))
    intent.db_set('status', 'Requested')
    intent.reload()

    return {
        'payment_intent': intent.name,
        'payment_link_url': intent.payment_link_url,
        'provider_link_id': intent.provider_link_id,
        'status': intent.status,
        'provider_status': intent.payment_status,
    }


@frappe.whitelist()
def get_payment_intent(payment_intent):
    doc = frappe.get_doc('Payment Intent', payment_intent)
    return doc.as_dict()


def _allow_partial(settings, reference_doctype):
    mapping = {
        'Lead': settings.lead_allow_partial_payment,
        'Patient Encounter': settings.encounter_allow_partial_payment,
        'Sales Order': settings.sales_order_allow_partial_payment,
        'Sales Invoice': settings.sales_invoice_allow_partial_payment,
    }
    return bool(mapping.get(reference_doctype))
