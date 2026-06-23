import frappe

from payment_orchestrator.provider.pinelabs.payment_link import PineLabsPaymentLinkAdapter
from payment_orchestrator.provider.razorpay.payment_link import RazorpayPaymentLinkAdapter
from payment_orchestrator.provider.razorpay.qr_code import RazorpayQRCodeAdapter
from payment_orchestrator.services import create_payment_intent_doc
from payment_orchestrator.utils import (
    get_settings,
    is_pinelabs_payment_link_enabled,
    is_razorpay_payment_link_enabled,
    is_razorpay_qr_code_enabled,
)


@frappe.whitelist()
def create_payment_intent(reference_doctype, reference_name, amount, request_type=None, request_channel=None, notes=None):
    return create_gateway_payment_link(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        gateway='Razorpay',
        request_type=request_type,
        request_channel=request_channel,
        notes=notes,
    )


@frappe.whitelist()
def create_gateway_payment_link(
    reference_doctype,
    reference_name,
    amount,
    gateway='Razorpay',
    request_type=None,
    request_channel=None,
    notes=None,
):
    amount = frappe.utils.flt(amount)
    if amount <= 0:
        frappe.throw('Amount must be greater than zero')

    settings = get_settings()
    gateway = gateway or 'Razorpay'
    if gateway == 'Razorpay':
        if not is_razorpay_payment_link_enabled(settings=settings):
            frappe.throw('Razorpay Payment Link is disabled in Payment Orchestrator Settings')
        adapter = RazorpayPaymentLinkAdapter(settings=settings)
    elif gateway in ('Pine Labs', 'PineLabs'):
        gateway = 'Pine Labs'
        if not is_pinelabs_payment_link_enabled(settings=settings):
            frappe.throw('Pine Labs Payment Link is disabled in Payment Orchestrator Settings')
        adapter = PineLabsPaymentLinkAdapter(settings=settings)
    else:
        frappe.throw(f'Unsupported payment-link gateway: {gateway}')

    if hasattr(adapter, 'ensure_available'):
        adapter.ensure_available()

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel=request_channel or 'Payment Link',
        notes=notes,
        gateway=gateway,
        payment_mode='Payment Link',
    )

    context["allow_partial"] = _allow_partial(settings, reference_doctype)
    adapter.create(intent, context)

    return {
        'payment_intent': intent.name,
        'gateway': intent.gateway,
        'payment_mode': intent.payment_mode,
        'payment_link_url': intent.payment_link_url,
        'provider_link_id': intent.provider_link_id,
        'status': intent.status,
        'provider_status': intent.payment_status,
    }


@frappe.whitelist()
def create_razorpay_qr_code(reference_doctype, reference_name, amount, request_type=None, notes=None):
    if reference_doctype not in ('Patient Encounter', 'Sales Order', 'Sales Invoice'):
        frappe.throw('Razorpay QR Code is available for Patient Encounter, Sales Order, and Sales Invoice')
    amount = frappe.utils.flt(amount)
    if amount <= 0:
        frappe.throw('Amount must be greater than zero')

    settings = get_settings()
    if not is_razorpay_qr_code_enabled(settings=settings):
        frappe.throw('Razorpay QR Code is disabled in Payment Orchestrator Settings')

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel='QR Code',
        notes=notes,
        gateway='Razorpay',
        payment_mode='QR Code',
    )

    response = RazorpayQRCodeAdapter(settings=settings).create(intent, context)

    return {
        'payment_intent': intent.name,
        'gateway': intent.gateway,
        'payment_mode': intent.payment_mode,
        'qr_code_url': intent.qr_code_url,
        'provider_qr_id': intent.provider_qr_id,
        'qr_status': intent.qr_status,
        'provider_status': intent.payment_status,
        'response': response,
    }


@frappe.whitelist()
def get_payment_intent(payment_intent):
    doc = frappe.get_doc('Payment Intent', payment_intent)
    return doc.as_dict()


def _allow_partial(settings, reference_doctype):
    mapping = {
        'CRM Lead': getattr(settings, 'crm_lead_allow_partial_payment', 1),
        'Patient Encounter': settings.encounter_allow_partial_payment,
        'Sales Order': settings.sales_order_allow_partial_payment,
        'Sales Invoice': settings.sales_invoice_allow_partial_payment,
    }
    return bool(mapping.get(reference_doctype))
