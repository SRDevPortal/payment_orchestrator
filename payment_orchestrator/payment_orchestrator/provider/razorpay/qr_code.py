from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.utils import as_json


class RazorpayQRCodeAdapter:
    gateway = "Razorpay"
    payment_mode = "QR Code"

    def __init__(self, settings):
        self.settings = settings
        self.client = RazorpayClient(settings=settings, mode=getattr(settings, "razorpay_qr_code_mode", None) or "Test")

    def create(self, intent, context):
        amount = int(round(float(intent.amount_requested or 0) * 100))
        payload = {
            "type": "upi_qr",
            "name": f"{intent.reference_doctype} {intent.reference_name}",
            "usage": "single_use",
            "fixed_amount": True,
            "payment_amount": amount,
            "description": f"{intent.reference_doctype} {intent.reference_name} - {intent.request_type}",
            "close_by": int(intent.expires_on.timestamp()) if intent.expires_on else None,
            "notes": {
                "payment_intent": intent.name,
                "reference_doctype": intent.reference_doctype,
                "reference_name": intent.reference_name,
                "request_type": intent.request_type,
                "party": context.get("party") or "",
            },
        }
        payload = {key: value for key, value in payload.items() if value is not None}
        response = self.client.create_qr_code(payload)

        intent.db_set("provider_payload_snapshot", as_json(response))
        intent.db_set("provider_qr_id", response.get("id"))
        intent.db_set("provider_request_id", response.get("id") or intent.name)
        intent.db_set("qr_code_url", response.get("image_url"))
        intent.db_set("qr_status", response.get("status"))
        intent.db_set("qr_close_by", response.get("close_by"))
        intent.db_set("payment_status", response.get("status"))
        intent.db_set("status", "Requested")
        intent.reload()

        return response
