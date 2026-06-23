import base64
import requests
import frappe


class RazorpayClient:
    def __init__(self, settings=None, mode=None):
        self.settings = settings or frappe.get_single('Payment Orchestrator Settings')
        self.mode = mode or 'Test'
        self.base_url = (self.settings.api_base_url or 'https://api.razorpay.com/v1').rstrip('/')
        self.pos_base_url = self.base_url

    def _auth_header(self):
        key_id = self._key_id()
        key_secret = self._key_secret()
        if not key_id or not key_secret:
            frappe.throw(f'Razorpay {self.mode} API Key ID and Secret are required')
        raw = f"{key_id}:{key_secret}".encode()
        token = base64.b64encode(raw).decode()
        return {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json',
        }

    def _key_id(self):
        if hasattr(self.settings, 'get_razorpay_key_id'):
            return self.settings.get_razorpay_key_id(self.mode)
        if self.mode == 'Live':
            return getattr(self.settings, 'razorpay_live_key_id', None) or getattr(self.settings, 'key_id', None)
        return getattr(self.settings, 'razorpay_test_key_id', None) or getattr(self.settings, 'key_id', None)

    def _key_secret(self):
        if hasattr(self.settings, 'get_razorpay_key_secret'):
            return self.settings.get_razorpay_key_secret(self.mode)
        fieldname = 'razorpay_live_key_secret' if self.mode == 'Live' else 'razorpay_test_key_secret'
        return (
            self.settings.get_password(fieldname, raise_exception=False)
            or self.settings.get_password('key_secret', raise_exception=False)
        )

    def _request(self, method, path, payload=None, timeout=30, base_url=None):
        response = requests.request(
            method=method,
            url=f'{base_url or self.base_url}{path}',
            json=payload,
            headers=self._auth_header(),
            timeout=timeout,
        )
        try:
            data = response.json()
        except Exception:
            data = {'raw': response.text}
        if response.status_code >= 400:
            frappe.throw(f'Razorpay API error ({response.status_code}): {data}')
        return data

    def validate_credentials(self):
        return self._request('GET', '/payments?count=1')

    def create_payment_link(self, payload):
        return self._request('POST', '/payment_links', payload=payload)

    def create_qr_code(self, payload):
        return self._request('POST', '/payments/qr_codes', payload=payload)

    def fetch_qr_code(self, qr_code_id):
        return self._request('GET', f'/payments/qr_codes/{qr_code_id}')

    def close_qr_code(self, qr_code_id):
        return self._request('POST', f'/payments/qr_codes/{qr_code_id}/close')

    def fetch_payment(self, payment_id):
        return self._request('GET', f'/payments/{payment_id}')

    def fetch_payment_link(self, payment_link_id):
        return self._request('GET', f'/payment_links/{payment_link_id}')

    def create_refund(self, payment_id, payload):
        return self._request('POST', f'/payments/{payment_id}/refund', payload=payload)

    def create_pos_payment_request(self, payload):
        timeout = int(getattr(self.settings, 'pos_timeout_seconds', None) or 30)
        return self._request('POST', '/pos/payment_requests', payload=payload, timeout=timeout, base_url=self.pos_base_url)

    def fetch_pos_payment_request(self, request_id):
        timeout = int(getattr(self.settings, 'pos_timeout_seconds', None) or 30)
        return self._request('GET', f'/pos/payment_requests/{request_id}', timeout=timeout, base_url=self.pos_base_url)
