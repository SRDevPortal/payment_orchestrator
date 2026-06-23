import frappe
from frappe.utils import get_datetime

from payment_orchestrator.provider.pinelabs.online import PineLabsOnlineClient
from payment_orchestrator.utils import as_json


class PineLabsPaymentLinkAdapter:
    gateway = "Pine Labs"
    payment_mode = "Payment Link"

    def __init__(self, settings):
        self.settings = settings
        self.client = PineLabsOnlineClient(settings=settings)

    def ensure_available(self):
        if not getattr(self.settings, "pinelabs_online_client_id", None):
            frappe.throw("Pine Labs Online Client ID is required for Payment Links")
        if not self.settings.get_password("pinelabs_online_client_secret", raise_exception=False):
            frappe.throw("Pine Labs Online Client Secret is required for Payment Links")

    def create(self, intent, context):
        self.ensure_available()
        response = self.client.create_payment_link(self.build_payload(intent, context))
        payment_link_id = response.get("payment_link_id") or response.get("id")
        payment_link_url = (
            response.get("payment_link")
            or response.get("payment_link_url")
            or response.get("short_url")
            or response.get("url")
        )

        intent.db_set("provider_payload_snapshot", as_json(response))
        intent.db_set("provider_link_id", payment_link_id)
        intent.db_set("provider_request_id", response.get("merchant_payment_link_reference") or intent.name)
        intent.db_set("payment_link_url", payment_link_url)
        intent.db_set("payment_status", response.get("status") or "CREATED")
        intent.db_set("status", "Requested")
        intent.reload()
        return response

    def build_payload(self, intent, context):
        amount = int(round(float(intent.amount_requested or 0) * 100))
        payload = {
            "amount": {
                "value": amount,
                "currency": intent.currency,
            },
            "description": f"{intent.reference_doctype} {intent.reference_name} - {intent.request_type}",
            "expire_by": _format_expiry(intent.expires_on),
            "allowed_payment_methods": _allowed_methods(self.settings),
            "pre_auth": "false",
            "is_mcc_transaction": "false",
            "merchant_payment_link_reference": intent.name,
            "customer": _customer_payload(intent, context),
            "merchant_metadata": {
                "payment_intent": intent.name,
                "reference_doctype": intent.reference_doctype,
                "reference_name": intent.reference_name,
                "request_type": intent.request_type,
            },
            "callback_url": getattr(self.settings, "pinelabs_payment_link_callback_url", None),
            "failure_callback_url": getattr(self.settings, "pinelabs_payment_link_failure_callback_url", None),
            "part_payment": bool(context.get("allow_partial")),
        }
        return _clean(payload)


def _format_expiry(value):
    if not value:
        return None
    return get_datetime(value).replace(microsecond=0).isoformat() + "Z"


def _allowed_methods(settings):
    raw = getattr(settings, "pinelabs_payment_link_allowed_methods", None) or "CARD,UPI"
    return [item.strip() for item in raw.split(",") if item.strip()]


def _customer_payload(intent, context):
    name = context.get("party_name") or intent.party_name or intent.reference_name
    parts = (name or "").split(None, 1)
    return _clean({
        "email_id": context.get("email") or intent.party_email,
        "first_name": parts[0] if parts else None,
        "last_name": parts[1] if len(parts) > 1 else None,
        "mobile_number": context.get("mobile") or intent.party_mobile,
        "country_code": "91",
        "merchant_customer_reference": context.get("party") or intent.party or intent.reference_name,
    })


def _clean(value):
    if isinstance(value, dict):
        return {key: _clean(item) for key, item in value.items() if item not in (None, "", [], {})}
    if isinstance(value, list):
        return [_clean(item) for item in value if item not in (None, "", [], {})]
    return value
