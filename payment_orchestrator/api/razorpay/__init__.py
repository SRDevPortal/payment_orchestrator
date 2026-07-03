import frappe
from frappe.utils import flt

from payment_orchestrator.logic import apply_unpaid_terminal_provider_status
from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.provider.razorpay.payment_link import RazorpayPaymentLinkAdapter
from payment_orchestrator.provider.razorpay.qr_code import RazorpayQRCodeAdapter
from payment_orchestrator.services import create_payment_intent_doc
from payment_orchestrator.utils import get_settings, is_razorpay_payment_link_enabled, is_razorpay_qr_code_enabled


@frappe.whitelist()
def create_payment_link(reference_doctype, reference_name, amount, request_type=None, request_channel=None, notes=None):
    amount = flt(amount)
    if amount <= 0:
        frappe.throw("Amount must be greater than zero")

    settings = get_settings()
    if not is_razorpay_payment_link_enabled(settings=settings):
        frappe.throw("Razorpay Payment Link is disabled in Payment Orchestrator Settings")

    from payment_orchestrator.api.common.validation import allow_partial, validate_reference_payment_request

    validate_reference_payment_request(reference_doctype, reference_name, amount, settings=settings)

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel=request_channel or "Payment Link",
        notes=notes,
        gateway="Razorpay",
        payment_mode="Payment Link",
    )

    context["allow_partial"] = allow_partial(settings, reference_doctype)
    RazorpayPaymentLinkAdapter(settings=settings).create(intent, context)

    return {
        "payment_intent": intent.name,
        "gateway": intent.gateway,
        "payment_mode": intent.payment_mode,
        "payment_link_url": intent.payment_link_url,
        "provider_link_id": intent.provider_link_id,
        "status": intent.status,
        "provider_status": intent.payment_status,
    }


@frappe.whitelist()
def create_qr_code(reference_doctype, reference_name, amount, request_type=None, notes=None):
    if reference_doctype not in ("Patient Encounter", "Sales Order", "Sales Invoice"):
        frappe.throw("Razorpay QR Code is available for Patient Encounter, Sales Order, and Sales Invoice")
    amount = flt(amount)
    if amount <= 0:
        frappe.throw("Amount must be greater than zero")

    settings = get_settings()
    if not is_razorpay_qr_code_enabled(settings=settings):
        frappe.throw("Razorpay QR Code is disabled in Payment Orchestrator Settings")

    from payment_orchestrator.api.common.validation import validate_reference_payment_request

    validate_reference_payment_request(reference_doctype, reference_name, amount, settings=settings)

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel="QR Code",
        notes=notes,
        gateway="Razorpay",
        payment_mode="QR Code",
    )

    response = RazorpayQRCodeAdapter(settings=settings).create(intent, context)

    return {
        "payment_intent": intent.name,
        "gateway": intent.gateway,
        "payment_mode": intent.payment_mode,
        "qr_code_url": intent.qr_code_url,
        "provider_qr_id": intent.provider_qr_id,
        "qr_status": intent.qr_status,
        "provider_status": intent.payment_status,
        "response": response,
    }


@frappe.whitelist()
def fetch_payment_link(payment_intent):
    intent = frappe.get_doc("Payment Intent", payment_intent)
    if intent.gateway != "Razorpay":
        frappe.throw("Payment Intent is not a Razorpay payment link")
    if not intent.provider_link_id:
        frappe.throw("Payment Intent has no provider link id")

    client = RazorpayClient(settings=get_settings(), mode=intent.provider_mode or "Test")
    data = client.fetch_payment_link(intent.provider_link_id)
    if not apply_unpaid_terminal_provider_status(intent, data.get("status"), data):
        intent.db_set("payment_status", data.get("status"))
        intent.db_set("provider_payload_snapshot", frappe.as_json(data))
    return data


@frappe.whitelist()
def fetch_qr_code(payment_intent):
    intent = frappe.get_doc("Payment Intent", payment_intent)
    if intent.gateway != "Razorpay":
        frappe.throw("Payment Intent is not a Razorpay QR Code")
    if not intent.provider_qr_id:
        frappe.throw("Payment Intent has no provider QR code id")
    client = RazorpayClient(settings=get_settings(), mode=intent.provider_mode or "Test")
    data = client.fetch_qr_code(intent.provider_qr_id)
    if not apply_unpaid_terminal_provider_status(intent, data.get("status"), data):
        intent.db_set("qr_status", data.get("status"))
        intent.db_set("payment_status", data.get("status"))
        intent.db_set("provider_payload_snapshot", frappe.as_json(data))
    return data


@frappe.whitelist()
def close_qr_code(payment_intent):
    intent = frappe.get_doc("Payment Intent", payment_intent)
    if intent.gateway != "Razorpay":
        frappe.throw("Payment Intent is not a Razorpay QR Code")
    if not intent.provider_qr_id:
        frappe.throw("Payment Intent has no provider QR code id")
    client = RazorpayClient(settings=get_settings(), mode=intent.provider_mode or "Test")
    data = client.close_qr_code(intent.provider_qr_id)
    if not apply_unpaid_terminal_provider_status(intent, data.get("status"), data):
        intent.db_set("qr_status", data.get("status"))
        intent.db_set("payment_status", data.get("status"))
        intent.db_set("provider_payload_snapshot", frappe.as_json(data))
    return data


@frappe.whitelist()
def refund_payment(payment_intent, amount=None, notes=None):
    settings = get_settings()
    if not settings.enable_refunds:
        frappe.throw("Refunds are disabled in settings")
    intent = frappe.get_doc("Payment Intent", payment_intent)
    if intent.gateway != "Razorpay":
        frappe.throw("Refunds through this endpoint are available only for Razorpay payments")
    if not intent.provider_payment_id:
        frappe.throw("Payment has not been captured for this intent yet")
    payload = {}
    if amount:
        payload["amount"] = int(round(flt(amount) * 100))
    if notes:
        payload["notes"] = {"reason": notes}
    client = RazorpayClient(settings=settings, mode=intent.provider_mode or "Test")
    response = client.create_refund(intent.provider_payment_id, payload)
    intent.db_set("payment_status", "refund_initiated")
    return response
