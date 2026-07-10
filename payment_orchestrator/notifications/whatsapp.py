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

    channel_account = None
    queued = {}
    sent_content_type = None
    try:
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
            fallback = send_payment_template_fallback_if_allowed(
                intent=intent,
                recipient=recipient,
                conversation=conversation,
                channel_account=channel_account,
                append_message=append_message,
                normal_error=result.get("error") or _("WhatsApp send failed"),
            )
            if fallback:
                queued = fallback["queued"]
                result = fallback["result"]
                sent_content_type = "Template"
            else:
                frappe.throw(result.get("error") or _("WhatsApp send failed"))

        delivery_status = (result.get("result") or {}).get("delivery_status") or "Sent"
        _update_payment_whatsapp_audit(
            intent,
            recipient=recipient,
            channel_account=channel_account,
            message=queued.get("message"),
            content_type=sent_content_type,
            status=delivery_status,
            error=None,
        )
        _add_payment_intent_comment(intent, recipient, queued, result)
        return {
            "ok": True,
            "payment_intent": intent.name,
            "conversation": conversation,
            "channel_account": channel_account,
            "message": queued.get("message"),
            "mobile_no": recipient["mobile_no"],
            "display_name": recipient.get("display_name"),
            "delivery_status": delivery_status,
            "content_type": sent_content_type,
        }
    except Exception as exc:
        _update_payment_whatsapp_audit(
            intent,
            recipient=recipient,
            channel_account=channel_account,
            message=queued.get("message") if queued else None,
            content_type=sent_content_type,
            status="Failed",
            error=str(exc),
        )
        raise


def send_payment_template_fallback_if_allowed(intent, recipient, conversation, channel_account, append_message, normal_error):
    if not is_template_fallback_error(normal_error):
        return None

    template = build_payment_template_payload(intent, recipient)
    if not template:
        return None
    if getattr(intent, "payment_mode", None) == "QR Code":
        template = with_qr_template_media(intent, channel_account, template)
    template = resolve_approved_payment_template(channel_account, template)

    from wa_chat_hub.outbound import send_interakt_template_message

    try:
        outbound = send_interakt_template_message(conversation, template)
    except Exception as exc:
        frappe.log_error(frappe.get_traceback(), f"Payment WhatsApp template fallback failed for {intent.name}")
        frappe.throw(_("WhatsApp template fallback failed after normal send failed: {0}").format(str(exc)))

    delivery_status = outbound.get("delivery_status") or "Sent"
    body_preview = template.get("body_preview") or f"Template: {template.get('template_name')}"
    queued = append_message({
        "channel_account": channel_account,
        "phone_number": recipient["mobile_no"],
        "display_name": recipient.get("display_name"),
        "direction": "Outbound",
        "sender_type": "Agent",
        "content_type": "Template",
        "body": body_preview,
        "delivery_status": delivery_status,
        "channel_message_id": outbound.get("provider_message_id"),
        "raw_transport_payload": {
            **outbound,
            "payment_intent": intent.name,
            "normal_send_error": str(normal_error or ""),
            "template_name": template.get("template_name"),
            "body_values": template.get("body_values"),
        },
    })
    return {
        "queued": queued,
        "normal_send_error": str(normal_error or ""),
        "result": {
            "success": True,
            "message": queued.get("message"),
            "normal_send_error": str(normal_error or ""),
            "result": {
                **outbound,
                "delivery_status": delivery_status,
                "normal_send_error": str(normal_error or ""),
            },
        },
    }


def resolve_approved_payment_template(channel_account, template):
    template_name = (template.get("template_name") or "").strip()
    language_code = (template.get("language_code") or "en").strip() or "en"
    if not template_name or not channel_account:
        return template

    approved_templates = fetch_approved_whatsapp_templates(channel_account, force_refresh=False)
    match = find_approved_whatsapp_template(approved_templates, template_name, language_code)
    if not match:
        approved_templates = fetch_approved_whatsapp_templates(channel_account, force_refresh=True)
        match = find_approved_whatsapp_template(approved_templates, template_name, language_code)

    if not match:
        available = ", ".join(
            sorted(
                {
                    f"{row.get('name')} ({row.get('language_code') or 'en'})"
                    for row in approved_templates
                    if row.get("name")
                }
            )
        )
        frappe.throw(
            _(
                "WhatsApp template '{0}' language '{1}' is not approved on channel '{2}'. "
                "Approved templates available: {3}. Update Payment Orchestrator Settings to the Interakt template name."
            ).format(template_name, language_code, channel_account, available or _("none"))
        )

    resolved_name = (match.get("name") or template_name).strip()
    if resolved_name != template_name:
        template = {**template, "template_name": resolved_name, "configured_template_name": template_name}
    return template


def fetch_approved_whatsapp_templates(channel_account, force_refresh=False):
    try:
        from wa_chat_hub.interakt.templates_api import fetch_approved_templates
    except Exception:
        return []

    return fetch_approved_templates(channel_account, force_refresh=force_refresh) or []


def find_approved_whatsapp_template(templates, template_name, language_code):
    wanted_name = (template_name or "").strip().lower()
    wanted_language = (language_code or "en").strip().lower() or "en"
    display_match = None

    for row in templates or []:
        name = (row.get("name") or "").strip()
        display_name = (row.get("display_name") or "").strip()
        languages = row.get("languages") or [row.get("language_code") or "en"]
        language_matches = wanted_language in {
            str(language or "en").strip().lower() or "en" for language in languages
        }
        if not language_matches:
            continue
        if name.lower() == wanted_name:
            return row
        if display_name.lower() == wanted_name and not display_match:
            display_match = row

    return display_match


def build_payment_template_payload(intent, recipient):
    settings = frappe.get_single("Payment Orchestrator Settings")
    if not getattr(settings, "enable_whatsapp_template_fallback", 0):
        return None

    template_name = payment_template_name_for_intent(settings, intent)
    if not template_name:
        frappe.throw(_("Payment Request WhatsApp template name is required for template fallback."))

    salutation_name = recipient.get("display_name") or intent.party_name or "Patient"
    company = getattr(intent, "company", None) or frappe.defaults.get_user_default("Company") or ""
    details = "Amount: {0} | Reference: {1}".format(
        format_amount(intent.amount_requested, intent.currency),
        f"{intent.reference_doctype} {intent.reference_name}".strip(),
    )
    payment_url = intent.payment_link_url or intent.qr_code_url
    if not payment_url:
        frappe.throw(_("Payment URL is required for WhatsApp template fallback."))

    body_values = [salutation_name, company, details, payment_url]
    is_qr = getattr(intent, "payment_mode", None) == "QR Code"
    return {
        "template_name": template_name,
        "language_code": (getattr(settings, "whatsapp_template_language", None) or "en").strip() or "en",
        "body_values": body_values,
        "body_preview": payment_template_body_preview(body_values, is_qr=is_qr),
        "template_category": "UTILITY",
    }


def payment_template_name_for_intent(settings, intent):
    link_template = (getattr(settings, "whatsapp_payment_request_template", None) or "").strip()
    if getattr(intent, "payment_mode", None) == "QR Code":
        return (getattr(settings, "whatsapp_qr_code_template", None) or "").strip() or link_template
    return link_template


def with_qr_template_media(intent, channel_account, template):
    media_url = interakt_qr_image_url(intent, channel_account)
    if not media_url:
        return template
    return {
        **template,
        "header_values": [media_url],
        "file_name": f"payment-qr-{intent.name}.png",
    }


def payment_template_body_preview(body_values, is_qr=False):
    name, company, details, payment_url = body_values
    payment_instruction_text = (
        "Please scan the QR image above or use the secure payment link below to complete your payment:"
        if is_qr
        else "Please use the secure payment link below to complete your payment:"
    )
    return "\n".join([
        f"Dear {name},",
        "",
        f"This is a payment request from {company}.",
        "",
        "Payment details:",
        details,
        "",
        payment_instruction_text,
        payment_url,
        "",
        "If you have already completed this payment, please ignore this message.",
        "",
        "Thank you.",
    ])


def is_template_fallback_error(error):
    text = str(error or "").lower()
    return any(
        marker in text
        for marker in (
            "24 hour",
            "24-hour",
            "24hours",
            "outside",
            "session",
            "template",
            "window",
            "free-text",
            "free text",
            "customer service",
        )
    )


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


def _update_payment_whatsapp_audit(intent, recipient, channel_account=None, message=None, content_type=None, status=None, error=None):
    try:
        values = payment_whatsapp_audit_values(
            recipient=recipient,
            channel_account=channel_account,
            message=message,
            content_type=content_type,
            status=status,
            error=error,
        )
        meta = frappe.get_meta("Payment Intent")
        values = {fieldname: value for fieldname, value in values.items() if meta.has_field(fieldname)}
        if values:
            frappe.db.set_value("Payment Intent", intent.name, values, update_modified=False)
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"Payment WhatsApp audit fields failed for {intent.name}")


def payment_whatsapp_audit_values(recipient, channel_account=None, message=None, content_type=None, status=None, error=None):
    return {
        "last_whatsapp_sent_on": now_datetime(),
        "last_whatsapp_recipient": (recipient or {}).get("mobile_no"),
        "last_whatsapp_channel_account": channel_account,
        "last_whatsapp_message": message,
        "last_whatsapp_content_type": content_type,
        "whatsapp_send_status": status,
        "last_whatsapp_error": error or None,
        "sent_via": "WhatsApp",
    }


def sync_payment_whatsapp_delivery_status(intent):
    message = getattr(intent, "last_whatsapp_message", None)
    if not message:
        return None
    if not frappe.db.exists("DocType", "Chat Message") or not frappe.db.exists("Chat Message", message):
        return None

    fields = ["delivery_status", "raw_payload", "raw_transport_payload"]
    meta = frappe.get_meta("Chat Message")
    fields = [field for field in fields if meta.has_field(field)]
    if not fields:
        return None

    row = frappe.db.get_value("Chat Message", message, fields, as_dict=True)
    values = payment_whatsapp_delivery_audit_values(row)
    if not values:
        return None

    intent_meta = frappe.get_meta("Payment Intent")
    values = {fieldname: value for fieldname, value in values.items() if intent_meta.has_field(fieldname)}
    if not values:
        return None

    values["last_synced_on"] = now_datetime()
    frappe.db.set_value("Payment Intent", intent.name, values, update_modified=False)
    return values


def sync_recent_payment_whatsapp_delivery_statuses(limit=100):
    if not frappe.db.exists("DocType", "Chat Message"):
        return {"updated": 0}

    rows = frappe.get_all(
        "Payment Intent",
        filters={"last_whatsapp_message": ["is", "set"]},
        fields=["name"],
        order_by="modified desc",
        limit=limit,
    )
    updated = 0
    for row in rows:
        try:
            intent = frappe.get_doc("Payment Intent", row.name)
            if sync_payment_whatsapp_delivery_status(intent):
                updated += 1
        except Exception:
            frappe.log_error(frappe.get_traceback(), f"Payment WhatsApp delivery sync failed for {row.name}")
    return {"updated": updated}


def payment_whatsapp_delivery_audit_values(chat_message):
    status = (getattr(chat_message, "delivery_status", None) or "").strip()
    if not status:
        return {}

    error = None
    if status == "Failed":
        error = extract_whatsapp_delivery_error(chat_message)

    return {
        "whatsapp_send_status": status,
        "last_whatsapp_error": error,
    }


def extract_whatsapp_delivery_error(chat_message):
    for fieldname in ("raw_payload", "raw_transport_payload"):
        raw_value = getattr(chat_message, fieldname, None)
        if not raw_value:
            continue
        try:
            payload = frappe.parse_json(raw_value)
        except Exception:
            payload = raw_value
        message = _extract_error_from_payload(payload)
        if message:
            return message
    return None


def _extract_error_from_payload(payload):
    if not payload:
        return None
    if isinstance(payload, str):
        return payload[:500]
    if not isinstance(payload, dict):
        return None

    for key in ("error", "message", "reason", "failure_reason", "failed_reason"):
        value = payload.get(key)
        if value:
            return _extract_error_from_payload(value) or str(value)[:500]

    for key in ("errors", "details"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return _extract_error_from_payload(value[0])
        if isinstance(value, dict):
            return _extract_error_from_payload(value)

    return None


def _ensure_wa_chat_hub_available():
    if not frappe.db.exists("DocType", "Chat Conversation"):
        frappe.throw(_("WA Chat Hub is not installed or Chat Conversation DocType is missing."))
