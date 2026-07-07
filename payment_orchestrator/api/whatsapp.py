import frappe
from frappe import _

from payment_orchestrator.api.common.validation import (
    ensure_payment_intent_action_permission,
    ensure_payment_intent_read_permission,
)
from payment_orchestrator.notifications.whatsapp import (
    build_payment_whatsapp_message,
    resolve_payment_whatsapp_recipient,
    send_payment_whatsapp_message,
)


@frappe.whitelist()
def send_payment_request(payment_intent, mobile_no=None):
    intent = frappe.get_doc("Payment Intent", payment_intent)
    ensure_payment_intent_action_permission(intent)
    ensure_whatsapp_supported_payment_intent(intent)
    try:
        return send_payment_whatsapp_message(intent, mobile_no=mobile_no)
    except Exception as exc:
        frappe.local.message_log = []
        return {
            "ok": False,
            "payment_intent": intent.name,
            "message": str(exc),
        }


@frappe.whitelist()
def get_payment_message_preview(payment_intent, mobile_no=None):
    intent = frappe.get_doc("Payment Intent", payment_intent)
    ensure_payment_intent_read_permission(intent)
    ensure_whatsapp_supported_payment_intent(intent)
    recipient = resolve_payment_whatsapp_recipient(intent, mobile_no=mobile_no)
    return {
        "ok": True,
        "payment_intent": intent.name,
        "message": build_payment_whatsapp_message(intent, recipient=recipient),
        "mobile_no": recipient.get("mobile_no"),
        "display_name": recipient.get("display_name"),
    }


def ensure_whatsapp_supported_payment_intent(intent):
    payment_mode = (intent.payment_mode or "").strip()
    if payment_mode == "Payment Link":
        if not intent.payment_link_url:
            frappe.throw(_("Payment Link WhatsApp message cannot be sent because payment link URL is missing."))
        return

    if payment_mode == "QR Code":
        if not intent.qr_code_url:
            frappe.throw(_("QR Code WhatsApp message cannot be sent because QR code URL is missing."))
        return

    frappe.throw(_("WhatsApp payment message is allowed only for Payment Link and QR Code payment intents."))
