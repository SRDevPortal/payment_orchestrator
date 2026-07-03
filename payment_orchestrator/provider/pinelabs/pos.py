from frappe.utils import flt, now_datetime
import frappe

from payment_orchestrator.provider.pinelabs.client import PineLabsClient
from payment_orchestrator.utils import as_json


class PineLabsPOSAdapter:
    gateway = "Pine Labs"
    payment_mode = "POS"

    def __init__(self, settings):
        self.settings = settings
        self.client = PineLabsClient(settings=settings)

    def upload_transaction(self, intent, invoice, context, client_id, allowed_payment_mode=None):
        amount = flt(intent.amount_requested)
        payload = {
            "TransactionNumber": intent.name,
            "SequenceNumber": 1,
            "AllowedPaymentMode": allowed_payment_mode or self.settings.pinelabs_allowed_payment_mode or "0",
            "Amount": int(round(amount * 100)),
            "TotalInvoiceAmount": int(round(flt(invoice.grand_total or amount) * 100)),
            "UserID": self.settings.pinelabs_user_id or frappe.session.user,
            "MerchantID": _numeric_if_digits(self.settings.pinelabs_merchant_id),
            "SecurityToken": self.settings.get_password("pinelabs_security_token"),
            "ClientId": _numeric_if_digits(client_id),
            "StoreId": _numeric_if_digits(self.settings.pinelabs_store_id),
            "AutoCancelDurationInMinutes": int(self.settings.pinelabs_auto_cancel_duration or 5),
            "CustomerMobileNumber": context.get("mobile") or "",
            "CustomerEmailID": context.get("email") or "",
            "InvoiceNumber": invoice.name,
            "invoicenumber": invoice.name,
        }
        response = self.client.upload_billed_transaction(payload)
        pos_request_id = self.extract_pos_request_id(response)
        if self.is_valid_pos_request_id(pos_request_id):
            intent.db_set("provider_payload_snapshot", as_json(response))
            intent.db_set("provider_pos_request_id", pos_request_id)
            intent.db_set("provider_request_id", pos_request_id or response.get("reference_id") or intent.name)
            intent.db_set("payment_status", response.get("ResponseMessage") or "APPROVED")
            intent.db_set("pos_request_status", "Uploaded")
            intent.db_set("last_synced_on", now_datetime())
        return response, pos_request_id

    def fetch_status(self, intent):
        response = self.client.get_transaction_status(intent.provider_pos_request_id, intent.name)
        intent.db_set("provider_payload_snapshot", as_json(response))
        intent.db_set("payment_status", response.get("ResponseMessage"))
        intent.db_set("pos_request_status", response.get("ResponseMessage"))
        intent.db_set("last_synced_on", now_datetime())
        return response

    @staticmethod
    def extract_pos_request_id(response):
        return (
            response.get("PlutusTransactionReferenceID")
            or response.get("plutusTransactionReferenceID")
            or response.get("plutus_transaction_reference_id")
        )

    @staticmethod
    def is_valid_pos_request_id(pos_request_id):
        try:
            return int(pos_request_id) > 0
        except Exception:
            return False


def _numeric_if_digits(value):
    value = str(value or "").strip()
    if value.isdigit():
        return int(value)
    return value
