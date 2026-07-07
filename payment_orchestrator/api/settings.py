import frappe

from payment_orchestrator.api.common.validation import ensure_payment_action_permission
from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.utils import (
    get_flag,
    get_public_webhook_url,
    is_pinelabs_payment_link_enabled,
    is_pinelabs_pos_enabled,
    is_razorpay_payment_link_enabled,
    is_razorpay_qr_code_enabled,
)


@frappe.whitelist()
def get_settings_context():
    doc = frappe.get_single('Payment Orchestrator Settings')
    return {
        'provider_enabled': get_flag(doc, 'provider_enabled'),
        'default_request_channel': doc.default_request_channel,
        'enable_on_crm_lead': get_flag(doc, 'enable_on_crm_lead', 1),
        'enable_on_patient_encounter': get_flag(doc, 'enable_on_patient_encounter', 1),
        'enable_on_sales_order': get_flag(doc, 'enable_on_sales_order', 1),
        'enable_on_sales_invoice': get_flag(doc, 'enable_on_sales_invoice', 1),
        'enable_auto_allocation': get_flag(doc, 'enable_auto_allocation', 1),
        'show_action_buttons': get_flag(doc, 'show_action_buttons', 1),
        'show_payment_summary_on_reference_doctypes': get_flag(doc, 'show_payment_summary_on_reference_doctypes', 1),
        'show_whatsapp_message_preview': get_flag(doc, 'show_whatsapp_message_preview'),
        'enable_razorpay': get_flag(doc, 'enable_razorpay', 1),
        'enable_razorpay_payment_link': is_razorpay_payment_link_enabled(settings=doc),
        'razorpay_payment_link_mode': getattr(doc, 'razorpay_payment_link_mode', None),
        'enable_razorpay_qr_code': is_razorpay_qr_code_enabled(settings=doc),
        'razorpay_qr_code_mode': getattr(doc, 'razorpay_qr_code_mode', None),
        'enable_razorpay_pos': get_flag(doc, 'enable_razorpay_pos'),
        'razorpay_pos_mode': getattr(doc, 'razorpay_pos_mode', None),
        'enable_pinelabs': get_flag(doc, 'enable_pinelabs', 1),
        'enable_pinelabs_payment_link': is_pinelabs_payment_link_enabled(settings=doc),
        'pinelabs_payment_link_mode': getattr(doc, 'pinelabs_payment_link_mode', None),
        'pinelabs_payment_link_after_payment_display': getattr(doc, 'pinelabs_payment_link_after_payment_display', None),
        'enable_pinelabs_pos': is_pinelabs_pos_enabled(settings=doc),
        'pinelabs_pos_mode': getattr(doc, 'pinelabs_pos_mode', None),
        'webhook_url': get_public_webhook_url(),
    }


@frappe.whitelist()
def test_provider_connection():
    ensure_payment_action_permission()
    settings = frappe.get_single('Payment Orchestrator Settings')
    mode = getattr(settings, 'razorpay_payment_link_mode', None) or 'Test'
    client = RazorpayClient(settings=settings, mode=mode)
    result = client.validate_credentials()
    return {
        'ok': True,
        'message': 'Razorpay credentials look valid.',
        'razorpay_payment_link_mode': mode,
        'result': result,
        'webhook_url': get_public_webhook_url(),
    }
