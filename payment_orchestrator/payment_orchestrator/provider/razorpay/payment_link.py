from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.utils import as_json


class RazorpayPaymentLinkAdapter:
    gateway = "Razorpay"
    payment_mode = "Payment Link"

    def __init__(self, settings):
        self.settings = settings
        self.client = RazorpayClient(settings=settings, mode=getattr(settings, "razorpay_payment_link_mode", None) or "Test")

    def create(self, intent, context):
        amount = int(round(float(intent.amount_requested or 0) * 100))
        payload = {
            "amount": amount,
            "currency": intent.currency,
            "accept_partial": 1 if context.get("allow_partial") else 0,
            "expire_by": int(intent.expires_on.timestamp()) if intent.expires_on else None,
            "reference_id": intent.name,
            "description": f"{intent.reference_doctype} {intent.reference_name} - {intent.request_type}",
            "customer": {
                "name": context.get("party_name") or intent.reference_name,
                "contact": context.get("mobile") or "",
                "email": context.get("email") or "",
            },
            "notify": {
                "sms": False,
                "email": False,
            },
            "notes": {
                "payment_intent": intent.name,
                "reference_doctype": intent.reference_doctype,
                "reference_name": intent.reference_name,
                "request_type": intent.request_type,
                "party": context.get("party") or "",
            },
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        response = self.client.create_payment_link(payload)

        intent.db_set("provider_payload_snapshot", as_json(response))
        intent.db_set("provider_link_id", response.get("id"))
        intent.db_set("provider_request_id", response.get("reference_id") or intent.name)
        intent.db_set("payment_link_url", response.get("short_url") or response.get("long_url"))
        intent.db_set("payment_status", response.get("status"))
        intent.db_set("status", "Requested")
        intent.reload()

        return response
