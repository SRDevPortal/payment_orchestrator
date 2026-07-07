import json
import hmac
import hashlib
from typing import Any

import frappe
from frappe.utils import now_datetime, get_url


REQUIRED_MODES_OF_PAYMENT = ("Razorpay", "Razorpay POS", "Pine Labs", "Pine Labs POS")


def get_settings():
    return frappe.get_single('Payment Orchestrator Settings')


def is_doctype_enabled(reference_doctype: str) -> bool:
    settings = get_settings()
    mapping = {
        'CRM Lead': get_flag(settings, 'enable_on_crm_lead', 1),
        'Patient Encounter': get_flag(settings, 'enable_on_patient_encounter', 1),
        'Sales Order': get_flag(settings, 'enable_on_sales_order', 1),
        'Sales Invoice': get_flag(settings, 'enable_on_sales_invoice', 1),
    }
    return bool(mapping.get(reference_doctype))


def get_default_request_type(reference_doctype: str) -> str:
    settings = get_settings()
    mapping = {
        'CRM Lead': getattr(settings, 'crm_lead_default_request_type', None),
        'Patient Encounter': getattr(settings, 'encounter_default_request_type', None),
        'Sales Order': getattr(settings, 'sales_order_default_request_type', None),
        'Sales Invoice': getattr(settings, 'sales_invoice_default_request_type', None),
    }
    return mapping.get(reference_doctype) or 'Advance'


def get_flag(settings, fieldname: str, default=0) -> int:
    value = getattr(settings, fieldname, None)
    if value is None:
        return default
    return 1 if bool(value) else 0


def is_gateway_enabled(gateway: str, settings=None) -> bool:
    settings = settings or get_settings()
    if not get_flag(settings, 'provider_enabled'):
        return False

    gateway = (gateway or '').lower().replace(' ', '_')
    mapping = {
        'razorpay': ('enable_razorpay', 1),
        'pine_labs': ('enable_pinelabs', 1),
        'pinelabs': ('enable_pinelabs', 1),
    }
    config = mapping.get(gateway)
    return bool(get_flag(settings, config[0], config[1])) if config else False


def is_gateway_mode_enabled(gateway: str, payment_mode: str, settings=None) -> bool:
    settings = settings or get_settings()
    if not is_gateway_enabled(gateway, settings=settings):
        return False

    gateway_key = (gateway or '').lower().replace(' ', '_')
    mode_key = (payment_mode or '').lower().replace(' ', '_')
    if mode_key in ('payment_link', 'payment_links'):
        if not get_flag(settings, 'enable_payment_links', 1):
            return False
        mode_key = 'payment_link'
    elif mode_key == 'pos':
        if not get_flag(settings, 'enable_pos_payments'):
            return False
    elif mode_key in ('qr_code', 'qr'):
        mode_key = 'qr_code'

    mapping = {
        ('razorpay', 'payment_link'): ('enable_razorpay_payment_link', 1),
        ('razorpay', 'qr_code'): ('enable_razorpay_qr_code', 0),
        ('razorpay', 'pos'): ('enable_razorpay_pos', 0),
        ('pine_labs', 'payment_link'): ('enable_pinelabs_payment_link', 0),
        ('pinelabs', 'payment_link'): ('enable_pinelabs_payment_link', 0),
        ('pine_labs', 'pos'): ('enable_pinelabs_pos', 1),
        ('pinelabs', 'pos'): ('enable_pinelabs_pos', 1),
    }
    config = mapping.get((gateway_key, mode_key))
    return bool(get_flag(settings, config[0], config[1])) if config else False


def get_provider_mode_for_gateway_mode(gateway: str, payment_mode: str, settings=None) -> str:
    settings = settings or get_settings()
    gateway_key = (gateway or '').lower().replace(' ', '_')
    mode_key = (payment_mode or '').lower().replace(' ', '_')
    if mode_key in ('payment_link', 'payment_links'):
        mode_key = 'payment_link'
    elif mode_key in ('qr_code', 'qr'):
        mode_key = 'qr_code'

    mapping = {
        ('razorpay', 'payment_link'): 'razorpay_payment_link_mode',
        ('razorpay', 'qr_code'): 'razorpay_qr_code_mode',
        ('razorpay', 'pos'): 'razorpay_pos_mode',
        ('pine_labs', 'payment_link'): 'pinelabs_payment_link_mode',
        ('pinelabs', 'payment_link'): 'pinelabs_payment_link_mode',
        ('pine_labs', 'pos'): 'pinelabs_pos_mode',
        ('pinelabs', 'pos'): 'pinelabs_pos_mode',
    }
    fieldname = mapping.get((gateway_key, mode_key))
    return getattr(settings, fieldname, None) or 'Test'


def is_razorpay_payment_link_enabled(settings=None) -> bool:
    return is_gateway_mode_enabled('Razorpay', 'Payment Link', settings=settings)


def is_razorpay_qr_code_enabled(settings=None) -> bool:
    return is_gateway_mode_enabled('Razorpay', 'QR Code', settings=settings)


def is_pinelabs_payment_link_enabled(settings=None) -> bool:
    return is_gateway_mode_enabled('Pine Labs', 'Payment Link', settings=settings)


def is_pinelabs_pos_enabled(settings=None) -> bool:
    return is_gateway_mode_enabled('Pine Labs', 'POS', settings=settings)


def is_razorpay_webhook_enabled(settings=None) -> bool:
    settings = settings or get_settings()
    return bool(
        is_gateway_enabled('Razorpay', settings=settings)
        and get_flag(settings, 'enable_webhook_processing', 1)
        and get_flag(settings, 'enable_razorpay_webhook_processing', 1)
    )


def is_pinelabs_postback_enabled(settings=None) -> bool:
    settings = settings or get_settings()
    return bool(
        is_gateway_enabled('Pine Labs', settings=settings)
        and get_flag(settings, 'enable_pinelabs_postback_processing', 1)
    )


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


def get_public_webhook_url(path: str = '/api/method/payment_orchestrator.api.webhooks.razorpay') -> str:
    return get_url(path)


def ensure_mode_of_payment(mode: str):
    mode = (mode or '').strip()
    if not mode:
        return None

    if not frappe.db.exists('Mode of Payment', mode):
        frappe.get_doc({
            'doctype': 'Mode of Payment',
            'mode_of_payment': mode,
            'enabled': 1,
        }).insert(ignore_permissions=True)
    return mode


def ensure_required_modes_of_payment():
    return [ensure_mode_of_payment(mode) for mode in REQUIRED_MODES_OF_PAYMENT]


def mode_of_payment_account(company: str, mode: str):
    if not company or not mode:
        return None

    account = frappe.db.get_value(
        'Mode of Payment Account',
        {'parent': mode, 'company': company},
        'default_account',
    )
    if not account and frappe.get_meta('Mode of Payment Account').has_field('account'):
        account = frappe.db.get_value(
            'Mode of Payment Account',
            {'parent': mode, 'company': company},
            'account',
        )
    return account


def now_ts():
    return now_datetime()
