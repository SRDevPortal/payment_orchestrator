import frappe

from razorpay_integration.provider.razorpay.client import RazorpayClient
from razorpay_integration.utils import get_public_webhook_url


@frappe.whitelist()
def get_settings_context():
    doc = frappe.get_single('Razorpay Integration Settings')
    return {
        'provider_enabled': doc.provider_enabled,
        'provider_mode': doc.provider_mode,
        'provider_name': doc.provider_name,
        'default_request_channel': doc.default_request_channel,
        'enable_on_lead': doc.enable_on_lead,
        'enable_on_patient_encounter': doc.enable_on_patient_encounter,
        'enable_on_sales_order': doc.enable_on_sales_order,
        'enable_on_sales_invoice': doc.enable_on_sales_invoice,
        'enable_auto_allocation': doc.enable_auto_allocation,
        'enable_settlement_sync': doc.enable_settlement_sync,
        'webhook_url': get_public_webhook_url(),
    }


@frappe.whitelist()
def test_provider_connection():
    settings = frappe.get_single('Razorpay Integration Settings')
    client = RazorpayClient(settings=settings)
    result = client.validate_credentials()
    return {
        'ok': True,
        'message': 'Razorpay credentials look valid.',
        'provider_mode': settings.provider_mode,
        'result': result,
        'webhook_url': get_public_webhook_url(),
    }
