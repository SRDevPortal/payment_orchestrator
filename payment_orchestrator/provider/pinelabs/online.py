import requests
import frappe


class PineLabsOnlineClient:
    def __init__(self, settings=None):
        self.settings = settings or frappe.get_single("Payment Orchestrator Settings")
        self.base_url = (
            getattr(self.settings, "pinelabs_online_base_url", None)
            or "https://pluraluat.v2.pinepg.in"
        ).rstrip("/")

    def generate_token(self):
        client_id = getattr(self.settings, "pinelabs_online_client_id", None)
        client_secret = self.settings.get_password("pinelabs_online_client_secret", raise_exception=False)
        if not client_id or not client_secret:
            frappe.throw("Pine Labs Online Client ID and Client Secret are required for Payment Links")

        path = getattr(self.settings, "pinelabs_online_auth_path", None) or "/api/auth/v1/token"
        response = self._request(
            "POST",
            path,
            payload={
                "client_id": client_id,
                "client_secret": client_secret,
                "grant_type": "client_credentials",
            },
            auth=False,
        )
        token = response.get("access_token")
        if not token:
            frappe.throw("Pine Labs token response did not include access_token")
        return token

    def create_payment_link(self, payload):
        path = getattr(self.settings, "pinelabs_payment_link_path", None) or "/api/pay/v1/paymentlink"
        return self._request("POST", path, payload=payload)

    def get_payment_link(self, payment_link_id):
        path = (getattr(self.settings, "pinelabs_payment_link_path", None) or "/api/pay/v1/paymentlink").rstrip("/")
        return self._request("GET", f"{path}/{payment_link_id}")

    def _request(self, method, path, payload=None, auth=True, timeout=30):
        headers = {"Content-Type": "application/json"}
        if auth:
            headers["Authorization"] = f"Bearer {self.generate_token()}"

        response = requests.request(
            method=method,
            url=f"{self.base_url}{path}",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        try:
            data = response.json()
        except Exception:
            data = {"raw": response.text}
        if response.status_code >= 400:
            frappe.throw(f"Pine Labs Online API error ({response.status_code}): {data}")
        return data
