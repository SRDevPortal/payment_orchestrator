from __future__ import annotations

import re

import frappe
import requests
from frappe import _
from frappe.utils import flt, now_datetime
from frappe.utils.file_manager import save_file


PHONE_FIELDS = ("mobile_no", "mobile", "phone", "phone_number", "contact_mobile", "custom_whatsapp_number")


def send_payment_whatsapp_message(intent, mobile_no=None):
    _ensure_wa_chat_hub_available()

    recipient = resolve_payment_whatsapp_recipient(intent, mobile_no=mobile_no)
    if not recipient.get("mobile_no"):
        return {
            "ok": False,
            "needs_mobile": True,
            "message": _("Mobile number is required to send WhatsApp notification."),
        }

    body = build_payment_whatsapp_message(intent, recipient=recipient)
    conversation = _get_or_create_payment_conversation(intent, recipient)
    channel_account = frappe.db.get_value("Chat Conversation", conversation, "channel_account")
    content_type, media_url = payment_whatsapp_transport(intent, channel_account)

    from wa_chat_hub.api.runtime import send_pending_reply_to_provider
    from wa_chat_hub.services import append_message

    queued = _append_payment_whatsapp_message(
        append_message=append_message,
        channel_account=channel_account,
        recipient=recipient,
        intent=intent,
        body=body,
        content_type=content_type,
        media_url=media_url,
    )
    sent_content_type = content_type
    result = send_pending_reply_to_provider(
        message_name=queued.get("message"),
        conversation=conversation,
        body=body,
        content_type=content_type,
        media_url=media_url,
        file_name=f"payment-qr-{intent.name}.png" if media_url else None,
    )

    if not result.get("success") and content_type == "Image":
        sent_content_type = "Text"
        queued = _append_payment_whatsapp_message(
            append_message=append_message,
            channel_account=channel_account,
            recipient=recipient,
            intent=intent,
            body=body,
            content_type="Text",
            media_url=None,
        )
        result = send_pending_reply_to_provider(
            message_name=queued.get("message"),
            conversation=conversation,
            body=body,
            content_type="Text",
        )

    if not result.get("success"):
        frappe.throw(result.get("error") or _("WhatsApp send failed"))

    _add_payment_intent_comment(intent, recipient, queued, result)
    return {
        "ok": True,
        "payment_intent": intent.name,
        "conversation": conversation,
        "channel_account": channel_account,
        "message": queued.get("message"),
        "mobile_no": recipient["mobile_no"],
        "display_name": recipient.get("display_name"),
        "delivery_status": (result.get("result") or {}).get("delivery_status") or "Sent",
        "content_type": sent_content_type,
    }


def _append_payment_whatsapp_message(append_message, channel_account, recipient, intent, body, content_type, media_url=None):
    return append_message({
        "channel_account": channel_account,
        "phone_number": recipient["mobile_no"],
        "display_name": recipient.get("display_name"),
        "direction": "Outbound",
        "sender_type": "Agent",
        "content_type": content_type,
        "body": body,
        "media_url": media_url,
        "delivery_status": "Pending",
        "raw_transport_payload": {
            "payment_intent": intent.name,
            "gateway": intent.gateway,
            "payment_mode": intent.payment_mode,
            "media_url": media_url,
        },
    })


def payment_whatsapp_transport(intent, channel_account):
    channel_type = frappe.db.get_value("Chat Channel Account", channel_account, "channel_type")
    if intent.payment_mode == "QR Code" and intent.qr_code_url and channel_type == "Interakt":
        media_url = interakt_qr_image_url(intent, channel_account)
        if media_url:
            return "Image", media_url
    return "Text", None


def interakt_qr_image_url(intent, channel_account):
    image = fetch_qr_image(intent)
    if not image:
        return None

    filename = f"payment-qr-{intent.name}.png"
    try:
        save_file(
            filename,
            image["content"],
            "Payment Intent",
            intent.name,
            decode=False,
            is_private=0,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"QR image local save failed for {intent.name}")

    try:
        return upload_interakt_media(
            channel_account=channel_account,
            filename=filename,
            content=image["content"],
            content_type=image["content_type"] or "image/png",
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Interakt QR media upload failed for {intent.name}")
        return None


def upload_interakt_media(channel_account, filename, content, content_type):
    from wa_chat_hub.interakt.account_config import media_upload_api_url

    account = frappe.get_doc("Chat Channel Account", channel_account)
    api_key = account.get_password("interakt_api_key")
    if not api_key:
        frappe.throw(_("Interakt API Key is not configured"))

    response = requests.post(
        media_upload_api_url(account),
        params={"fileCategory": "message_template_media"},
        headers={"Authorization": f"Basic {api_key}"},
        files={"uploadFile": (filename, content, content_type or "image/png")},
        timeout=30,
    )
    if not response.ok:
        frappe.log_error(
            f"Interakt Media Upload Error {response.status_code}: {response.text}",
            "Interakt Media Upload Failure",
        )
    response.raise_for_status()

    result = response.json() if response.content else {}
    data = result.get("data") if isinstance(result, dict) else {}
    media_url = (data or {}).get("file_url")
    if not media_url:
        frappe.throw(_("Interakt did not return a media URL"))
    return media_url


def fetch_qr_image(intent):
    if not intent.qr_code_url or not _is_safe_qr_url(intent.qr_code_url):
        return None

    try:
        response = requests.get(intent.qr_code_url, timeout=15, allow_redirects=True)
        response.raise_for_status()
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"QR image fetch failed for {intent.name}")
        return None

    content_type = (response.headers.get("Content-Type") or "").split(";")[0].strip().lower()
    if content_type and not content_type.startswith("image/"):
        frappe.log_error(
            f"QR URL did not return an image. URL: {intent.qr_code_url}, Content-Type: {content_type}",
            f"QR image fetch failed for {intent.name}",
        )
        return None

    return {
        "content": response.content,
        "content_type": content_type or "image/png",
        "source_url": response.url,
    }


def _is_safe_qr_url(url):
    value = str(url or "").strip().lower()
    return value.startswith("https://") and (
        "rzp.io/" in value
        or "razorpay.com/" in value
        or "razorpay" in value
    )


def resolve_payment_whatsapp_recipient(intent, mobile_no=None):
    explicit_mobile = normalize_mobile(mobile_no)
    if explicit_mobile:
        return {
            "mobile_no": explicit_mobile,
            "display_name": intent.party_name or intent.party or intent.reference_name,
            "source": "manual",
        }

    candidates = [
        (getattr(intent, "party_mobile", None), intent.party_name or intent.party, "payment_intent"),
    ]
    candidates.extend(_reference_mobile_candidates(intent))
    candidates.extend(_linked_party_mobile_candidates(intent))

    for phone, display_name, source in candidates:
        normalized = normalize_mobile(phone)
        if normalized:
            return {
                "mobile_no": normalized,
                "display_name": display_name or intent.party_name or intent.party or intent.reference_name,
                "source": source,
            }

    return {"mobile_no": None, "display_name": intent.party_name or intent.party or intent.reference_name}


def build_payment_whatsapp_message(intent, recipient=None):
    recipient = recipient or {}
    salutation_name = recipient.get("display_name") or intent.party_name or "Patient"
    amount = format_amount(intent.amount_requested, intent.currency)
    reference = f"{intent.reference_doctype} {intent.reference_name}".strip()
    company = getattr(intent, "company", None) or frappe.defaults.get_user_default("Company") or ""
    instruction = payment_instruction(intent)

    lines = [
        f"Dear {salutation_name},",
        f"Your payment request of {amount} is ready.",
        "",
        instruction,
        "",
        f"Reference: {reference}",
    ]
    if company:
        lines.append(company)
    return "\n".join(line for line in lines if line is not None)


def payment_instruction(intent):
    if intent.payment_mode == "POS":
        return "Please complete the payment at the POS terminal/counter."
    if intent.payment_link_url:
        return f"Pay here:\n{intent.payment_link_url}"
    if intent.qr_code_url:
        return f"Scan/pay here:\n{intent.qr_code_url}"
    return "Please contact the billing desk to complete payment."


def format_amount(value, currency=None):
    amount = flt(value or 0)
    symbol = "₹" if (currency or "INR") == "INR" else (currency or "INR")
    return f"{symbol} {amount:,.2f}"


def normalize_mobile(value):
    digits = re.sub(r"\D", "", str(value or ""))
    if not digits:
        return ""
    if len(digits) == 10:
        return f"91{digits}"
    return digits


def _reference_mobile_candidates(intent):
    candidates = []
    if not intent.reference_doctype or not intent.reference_name or not frappe.db.exists(intent.reference_doctype, intent.reference_name):
        return candidates

    doc = frappe.get_doc(intent.reference_doctype, intent.reference_name)
    candidates.extend(_doc_mobile_candidates(doc, "reference"))

    patient = getattr(doc, "patient", None)
    if patient and frappe.db.exists("Patient", patient):
        patient_doc = frappe.get_doc("Patient", patient)
        candidates.extend(_doc_mobile_candidates(patient_doc, "patient"))

    customer = getattr(doc, "customer", None)
    if customer and frappe.db.exists("Customer", customer):
        customer_doc = frappe.get_doc("Customer", customer)
        candidates.extend(_doc_mobile_candidates(customer_doc, "customer"))

    return candidates


def _linked_party_mobile_candidates(intent):
    candidates = []
    if getattr(intent, "patient", None) and frappe.db.exists("Patient", intent.patient):
        candidates.extend(_doc_mobile_candidates(frappe.get_doc("Patient", intent.patient), "intent_patient"))
    if getattr(intent, "party_type", None) == "Customer" and getattr(intent, "party", None) and frappe.db.exists("Customer", intent.party):
        candidates.extend(_doc_mobile_candidates(frappe.get_doc("Customer", intent.party), "intent_customer"))
    return candidates


def _doc_mobile_candidates(doc, source):
    candidates = []
    display_name = (
        getattr(doc, "patient_name", None)
        or getattr(doc, "customer_name", None)
        or getattr(doc, "lead_name", None)
        or getattr(doc, "full_name", None)
        or getattr(doc, "name", None)
    )
    for fieldname in PHONE_FIELDS:
        if hasattr(doc, fieldname):
            candidates.append((getattr(doc, fieldname, None), display_name, source))
    return candidates


def _get_or_create_payment_conversation(intent, recipient):
    from wa_chat_hub.services import get_or_create_contact, get_or_create_conversation

    contact = get_or_create_contact(
        phone_number=recipient["mobile_no"],
        display_name=recipient.get("display_name") or recipient["mobile_no"],
    )
    channel_account = resolve_payment_channel_account(recipient, contact=contact)
    conversation = get_or_create_conversation(channel_account=channel_account, contact=contact)
    _link_conversation_reference(conversation, intent)
    return conversation


def resolve_payment_channel_account(recipient, contact=None):
    existing_account = _existing_payment_conversation_channel_account(recipient, contact=contact)
    if existing_account:
        return existing_account

    default_account = _default_payment_whatsapp_channel_account()
    if default_account:
        return default_account

    frappe.throw(
        _(
            "No active WhatsApp conversation found for this patient, and no default WhatsApp channel is configured in Payment Orchestrator Settings."
        )
    )


def _existing_payment_conversation_channel_account(recipient, contact=None):
    contact = contact or _chat_contact_for_mobile(recipient.get("mobile_no"))
    if not contact:
        return None

    fields = ["name", "channel_account", "modified"]
    if frappe.get_meta("Chat Conversation").has_field("status"):
        filters = {"contact": contact, "status": ["!=", "Closed"]}
    else:
        filters = {"contact": contact}

    for row in frappe.get_all(
        "Chat Conversation",
        filters=filters,
        fields=fields,
        order_by="modified desc",
        limit=20,
    ):
        if _is_valid_payment_channel_account(row.channel_account):
            return row.channel_account
    return None


def _chat_contact_for_mobile(mobile_no):
    if not mobile_no:
        return None
    return frappe.db.get_value("Chat Contact", {"phone_number": normalize_mobile(mobile_no)}, "name")


def _default_payment_whatsapp_channel_account():
    settings = frappe.get_single("Payment Orchestrator Settings")
    channel_account = getattr(settings, "default_whatsapp_channel_account", None)
    if not channel_account:
        return None
    if not _is_valid_payment_channel_account(channel_account):
        frappe.throw(
            _("Default WhatsApp Channel Account {0} is inactive, disconnected, or not an Interakt account.").format(
                channel_account
            )
        )
    return channel_account


def _is_valid_payment_channel_account(channel_account):
    if not channel_account:
        return False

    account = frappe.db.get_value(
        "Chat Channel Account",
        channel_account,
        ["channel_type", "is_active", "connector_status"],
        as_dict=True,
    )
    if not account:
        return False
    if account.channel_type != "Interakt":
        return False
    if not account.is_active:
        return False
    if account.connector_status and account.connector_status != "Active":
        return False
    return True


def _link_conversation_reference(conversation, intent):
    updates = {}
    meta = frappe.get_meta("Chat Conversation")
    if meta.has_field("linked_reference_doctype"):
        updates["linked_reference_doctype"] = intent.reference_doctype
    if meta.has_field("linked_reference_name"):
        updates["linked_reference_name"] = intent.reference_name
    if intent.reference_doctype == "CRM Lead" and meta.has_field("linked_crm_lead"):
        updates["linked_crm_lead"] = intent.reference_name
    if updates:
        frappe.db.set_value("Chat Conversation", conversation, updates, update_modified=False)


def _add_payment_intent_comment(intent, recipient, queued, result):
    try:
        intent.add_comment(
            "Info",
            _("WhatsApp payment request sent to {0}. Message: {1}. Status: {2}").format(
                recipient.get("mobile_no"),
                queued.get("message"),
                (result.get("result") or {}).get("delivery_status") or "Sent",
            ),
        )
        frappe.db.set_value("Payment Intent", intent.name, "last_synced_on", now_datetime(), update_modified=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Payment WhatsApp audit failed for {intent.name}")


def _ensure_wa_chat_hub_available():
    if not frappe.db.exists("DocType", "Chat Conversation"):
        frappe.throw(_("WA Chat Hub is not installed or Chat Conversation DocType is missing."))
