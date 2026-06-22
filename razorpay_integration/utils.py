import json
import hmac
import hashlib
from typing import Any

import frappe
from frappe.utils import now_datetime, get_url


def get_settings():
    return frappe.get_single('Razorpay Integration Settings')


def is_doctype_enabled(reference_doctype: str) -> bool:
    settings = get_settings()
    mapping = {
        'Lead': settings.enable_on_lead,
        'Patient Encounter': settings.enable_on_patient_encounter,
        'Sales Order': settings.enable_on_sales_order,
        'Sales Invoice': settings.enable_on_sales_invoice,
    }
    return bool(mapping.get(reference_doctype))


def get_default_request_type(reference_doctype: str) -> str:
    settings = get_settings()
    mapping = {
        'Lead': settings.lead_default_request_type,
        'Patient Encounter': settings.encounter_default_request_type,
        'Sales Order': settings.sales_order_default_request_type,
        'Sales Invoice': settings.sales_invoice_default_request_type,
    }
    return mapping.get(reference_doctype) or 'Advance'


def as_json(data: Any) -> str:
    try:
        return json.dumps(data, default=str, ensure_ascii=False)
    except Exception:
        return json.dumps({'repr': repr(data)})


def verify_razorpay_webhook_signature(payload: str, signature: str, secret: str) -> bool:
    digest = hmac.new(
        key=(secret or '').encode('utf-8'),
        msg=(payload or '').encode('utf-8'),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(digest, signature or '')


def get_public_webhook_url(path: str = '/api/method/razorpay_integration.api.webhooks.razorpay') -> str:
    return get_url(path)


def now_ts():
    return now_datetime()
