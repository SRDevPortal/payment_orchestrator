import requests
import frappe


class PineLabsClient:
    def __init__(self, settings=None):
        self.settings = settings or frappe.get_single("Razorpay Integration Settings")
        self.base_url = (
            getattr(self.settings, "pinelabs_base_url", None)
            or "https://www.plutuscloudserviceuat.in:8201"
        ).rstrip("/")

    def _request(self, path, payload=None, timeout=30):
        response = requests.post(
            url=f"{self.base_url}{path}",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=timeout,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        if response.status_code >= 400:
            frappe.throw(f"Pine Labs API error ({response.status_code}): {data}")
        return data

    def upload_billed_transaction(self, payload):
        path = getattr(self.settings, "pinelabs_upload_path", None) or "/API/CloudBasedIntegration/V1/UploadBilledTransaction"
        timeout = int(getattr(self.settings, "pos_timeout_seconds", None) or 30)
        return self._request(path, payload=payload, timeout=timeout)

    def get_transaction_status(self, plutus_transaction_reference_id, transaction_number=None):
        path = getattr(self.settings, "pinelabs_status_path", None) or "/API/CloudBasedIntegration/V1/GetCloudBasedTxnStatus"
        timeout = int(getattr(self.settings, "pos_timeout_seconds", None) or 30)
        payload = {
            "MerchantID": getattr(self.settings, "pinelabs_merchant_id", None),
            "SecurityToken": self.settings.get_password("pinelabs_security_token"),
            "StoreID": getattr(self.settings, "pinelabs_store_id", None),
            "ClientID": getattr(self.settings, "pinelabs_client_id", None),
            "UserID": getattr(self.settings, "pinelabs_user_id", None) or frappe.session.user,
            "PlutusTransactionReferenceID": plutus_transaction_reference_id,
        }
        if transaction_number:
            payload["TransactionNumber"] = transaction_number
        return self._request(path, payload=payload, timeout=timeout)

    def cancel_transaction(self, plutus_transaction_reference_id, amount):
        path = getattr(self.settings, "pinelabs_cancel_path", None) or "/API/CloudBasedIntegration/V1/CancelTransaction"
        timeout = int(getattr(self.settings, "pos_timeout_seconds", None) or 30)
        payload = {
            "MerchantID": getattr(self.settings, "pinelabs_merchant_id", None),
            "SecurityToken": self.settings.get_password("pinelabs_security_token"),
            "StoreID": getattr(self.settings, "pinelabs_store_id", None),
            "ClientID": getattr(self.settings, "pinelabs_client_id", None),
            "PlutusTransactionReferenceID": plutus_transaction_reference_id,
            "Amount": int(round(float(amount or 0) * 100)),
        }
        return self._request(path, payload=payload, timeout=timeout)
