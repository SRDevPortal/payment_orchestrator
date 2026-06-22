import base64
import requests
import frappe


class RazorpayClient:
    def __init__(self, settings=None):
        self.settings = settings or frappe.get_single('Razorpay Integration Settings')
        self.base_url = (self.settings.api_base_url or 'https://api.razorpay.com/v1').rstrip('/')
        self.pos_base_url = (getattr(self.settings, 'pos_api_base_url', None) or self.base_url).rstrip('/')

    def _auth_header(self):
        raw = f"{self.settings.key_id}:{self.settings.get_password('key_secret')}".encode()
        token = base64.b64encode(raw).decode()
        return {
            'Authorization': f'Basic {token}',
            'Content-Type': 'application/json',
        }

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

    def fetch_payment(self, payment_id):
        return self._request('GET', f'/payments/{payment_id}')

    def fetch_payment_link(self, payment_link_id):
        return self._request('GET', f'/payment_links/{payment_link_id}')

    def create_refund(self, payment_id, payload):
        return self._request('POST', f'/payments/{payment_id}/refund', payload=payload)

    def create_pos_payment_request(self, payload):
        path = getattr(self.settings, 'pos_create_request_path', None) or '/pos/payment_requests'
        timeout = int(getattr(self.settings, 'pos_timeout_seconds', None) or 30)
        return self._request('POST', path, payload=payload, timeout=timeout, base_url=self.pos_base_url)

    def fetch_pos_payment_request(self, request_id):
        path_template = getattr(self.settings, 'pos_fetch_request_path', None) or '/pos/payment_requests/{request_id}'
        path = path_template.format(request_id=request_id)
        timeout = int(getattr(self.settings, 'pos_timeout_seconds', None) or 30)
        return self._request('GET', path, timeout=timeout, base_url=self.pos_base_url)
