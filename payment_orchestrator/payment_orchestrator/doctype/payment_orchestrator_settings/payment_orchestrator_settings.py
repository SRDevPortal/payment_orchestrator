import frappe
from frappe.model.document import Document
from frappe.utils import cint
from frappe.utils.password import remove_encrypted_password


RAZORPAY_API_BASE_URL = "https://api.razorpay.com/v1"
PINELABS_BASE_URL = "https://www.plutuscloudserviceuat.in:8201"
PINELABS_PRODUCTION_BASE_URL = "https://www.plutuscloudservice.in:8201"
PINELABS_UPLOAD_PATH = "/API/CloudBasedIntegration/V1/UploadBilledTransaction"
PINELABS_STATUS_PATH = "/API/CloudBasedIntegration/V1/GetCloudBasedTxnStatus"
PINELABS_CANCEL_PATH = "/API/CloudBasedIntegration/V1/CancelTransaction"
PINELABS_ONLINE_BASE_URL = "https://pluraluat.v2.pinepg.in"
PINELABS_ONLINE_AUTH_PATH = "/api/auth/v1/token"
PINELABS_PAYMENT_LINK_PATH = "/api/pay/v1/paymentlink"
PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY = "Pine Labs Default Page"


class PaymentOrchestratorSettings(Document):
	def validate(self):
		self.enable_razorpay = 1 if self.enable_razorpay is None else self.enable_razorpay
		self.enable_razorpay_payment_link = 1 if self.enable_razorpay_payment_link is None else self.enable_razorpay_payment_link
		self.enable_razorpay_qr_code = self.enable_razorpay_qr_code or 0
		self.enable_razorpay_pos = self.enable_razorpay_pos or 0
		self.enable_razorpay_webhook_processing = 1 if self.enable_razorpay_webhook_processing is None else self.enable_razorpay_webhook_processing
		self.razorpay_payment_link_mode = self.razorpay_payment_link_mode or "Test"
		self.razorpay_qr_code_mode = self.razorpay_qr_code_mode or "Test"
		self.razorpay_pos_mode = self.razorpay_pos_mode or "Test"
		self.enable_pinelabs = 1 if self.enable_pinelabs is None else self.enable_pinelabs
		self.enable_pinelabs_payment_link = self.enable_pinelabs_payment_link or 0
		self.enable_pinelabs_pos = 1 if self.enable_pinelabs_pos is None else self.enable_pinelabs_pos
		self.enable_pinelabs_postback_processing = 1 if self.enable_pinelabs_postback_processing is None else self.enable_pinelabs_postback_processing
		self.pinelabs_pos_mode = self.pinelabs_pos_mode or "Test"
		self.pinelabs_payment_link_mode = self.pinelabs_payment_link_mode or "Test"
		if cint(self.enable_razorpay_pos) or cint(self.enable_pinelabs_pos):
			self.enable_pos_payments = 1
		self.pinelabs_payment_link_after_payment_display = self.pinelabs_payment_link_after_payment_display or PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY
		if not self.api_base_url or "api.payment_orchestrator.com" in self.api_base_url:
			self.api_base_url = RAZORPAY_API_BASE_URL
		self.api_base_url = self.api_base_url.rstrip("/")
		self.default_currency = self.default_currency or "INR"
		self.default_request_channel = self.default_request_channel or "Payment Link"
		self.whatsapp_payment_request_template = self.whatsapp_payment_request_template or "payment_request"
		self.whatsapp_template_language = self.whatsapp_template_language or "en"
		self.default_mode_of_payment = self.default_mode_of_payment or "Razorpay"
		self.pos_timeout_seconds = max(int(self.pos_timeout_seconds or 30), 1)
		self.pos_mode_of_payment = self.pos_mode_of_payment or "Pine Labs POS"
		if self.default_pos_device_id:
			self.pinelabs_client_id = self.default_pos_device_id
		elif self.pinelabs_client_id:
			self.default_pos_device_id = self.pinelabs_client_id
		self.set_pinelabs_pos_base_url()
		self.pinelabs_upload_path = self.pinelabs_upload_path or PINELABS_UPLOAD_PATH
		self.pinelabs_status_path = self.pinelabs_status_path or PINELABS_STATUS_PATH
		self.pinelabs_cancel_path = self.pinelabs_cancel_path or PINELABS_CANCEL_PATH
		self.pinelabs_online_base_url = (self.pinelabs_online_base_url or PINELABS_ONLINE_BASE_URL).rstrip("/")
		self.pinelabs_online_auth_path = self.pinelabs_online_auth_path or PINELABS_ONLINE_AUTH_PATH
		self.pinelabs_payment_link_path = self.pinelabs_payment_link_path or PINELABS_PAYMENT_LINK_PATH
		self.pinelabs_payment_link_allowed_methods = self.pinelabs_payment_link_allowed_methods or "CARD,UPI"
		self.pinelabs_allowed_payment_mode = self.pinelabs_allowed_payment_mode or "0"
		self.pinelabs_upi_qr_payment_mode_code = self.pinelabs_upi_qr_payment_mode_code or "10"
		self.pinelabs_auto_cancel_duration = max(int(self.pinelabs_auto_cancel_duration or 5), 1)
		self.payment_link_expiry_hours = max(int(self.payment_link_expiry_hours or 72), 1)
		self.reset_inactive_gateway_fields()

		if self.provider_enabled and self.enable_razorpay and not self.has_razorpay_credentials_for_active_modes():
			frappe.msgprint("Razorpay is enabled but API credentials are missing for one or more active Razorpay modes.")

	def on_update(self):
		from payment_orchestrator.setup.install import (
			sync_reference_field_placement,
			sync_reference_field_visibility,
		)

		sync_reference_field_placement()
		sync_reference_field_visibility()

	def reset_inactive_gateway_fields(self):
		self.reset_inactive_razorpay_fields()
		self.reset_inactive_pinelabs_fields()

	def reset_inactive_razorpay_fields(self):
		if not cint(self.enable_razorpay):
			self.enable_razorpay_payment_link = 0
			self.enable_razorpay_qr_code = 0
			self.enable_razorpay_pos = 0
			self.enable_razorpay_webhook_processing = 0

		razorpay_link_active = cint(self.enable_razorpay) and cint(self.enable_razorpay_payment_link)
		razorpay_qr_active = cint(self.enable_razorpay) and cint(self.enable_razorpay_qr_code)
		razorpay_pos_active = cint(self.enable_razorpay) and cint(self.enable_razorpay_pos)
		razorpay_webhook_active = cint(self.enable_razorpay) and cint(self.enable_razorpay_webhook_processing)

		if not razorpay_link_active:
			self.razorpay_payment_link_mode = "Test"

		if not razorpay_qr_active:
			self.razorpay_qr_code_mode = "Test"

		if not razorpay_pos_active:
			self.razorpay_pos_mode = "Test"

		if not (razorpay_link_active or razorpay_qr_active or razorpay_pos_active):
			self.razorpay_test_key_id = None
			self.razorpay_live_key_id = None
			self.clear_secret("razorpay_test_key_secret")
			self.clear_secret("razorpay_live_key_secret")
			self.api_base_url = RAZORPAY_API_BASE_URL

		if not razorpay_webhook_active:
			self.clear_secret("webhook_secret")

	def has_razorpay_credentials_for_active_modes(self):
		required_modes = []
		if cint(self.enable_razorpay_payment_link):
			required_modes.append(self.razorpay_payment_link_mode)
		if cint(self.enable_razorpay_qr_code):
			required_modes.append(self.razorpay_qr_code_mode)
		if cint(self.enable_razorpay_pos):
			required_modes.append(self.razorpay_pos_mode)

		for mode in set(required_modes):
			if not self.get_razorpay_key_id(mode) or not self.get_razorpay_key_secret(mode):
				return False
		return True

	def get_razorpay_key_id(self, mode):
		mode = mode or "Test"
		if mode == "Live":
			return self.razorpay_live_key_id or self.key_id
		return self.razorpay_test_key_id or self.key_id

	def get_razorpay_key_secret(self, mode):
		mode = mode or "Test"
		if mode == "Live":
			return self.get_password("razorpay_live_key_secret", raise_exception=False) or self.get_password("key_secret", raise_exception=False)
		return self.get_password("razorpay_test_key_secret", raise_exception=False) or self.get_password("key_secret", raise_exception=False)

	def reset_inactive_pinelabs_fields(self):
		if not cint(self.enable_pinelabs):
			self.enable_pinelabs_payment_link = 0
			self.enable_pinelabs_pos = 0
			self.enable_pinelabs_postback_processing = 0

		pinelabs_link_active = cint(self.enable_pinelabs) and cint(self.enable_pinelabs_payment_link)
		pinelabs_pos_active = cint(self.enable_pinelabs) and cint(self.enable_pinelabs_pos)

		if not pinelabs_link_active:
			self.pinelabs_payment_link_mode = "Test"
			self.pinelabs_online_client_id = None
			self.clear_secret("pinelabs_online_client_secret")
			self.pinelabs_online_base_url = PINELABS_ONLINE_BASE_URL
			self.pinelabs_online_auth_path = PINELABS_ONLINE_AUTH_PATH
			self.pinelabs_payment_link_path = PINELABS_PAYMENT_LINK_PATH
			self.pinelabs_payment_link_allowed_methods = "CARD,UPI"
			self.pinelabs_payment_link_after_payment_display = PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY
			self.pinelabs_payment_link_callback_url = None
			self.pinelabs_payment_link_failure_callback_url = None

		if not pinelabs_pos_active:
			self.pinelabs_pos_mode = "Test"
			self.pinelabs_merchant_id = None
			self.pinelabs_merchant_name = None
			self.clear_secret("pinelabs_security_token")
			self.pinelabs_store_id = None
			self.pinelabs_store_name = None
			self.pinelabs_client_id = None
			self.pinelabs_device_no = None
			self.pinelabs_user_id = None
			self.pinelabs_allowed_payment_mode = "0"
			self.pinelabs_auto_cancel_duration = 5
			self.pinelabs_base_url = PINELABS_BASE_URL
			self.pinelabs_upload_path = PINELABS_UPLOAD_PATH
			self.pinelabs_status_path = PINELABS_STATUS_PATH
			self.pinelabs_cancel_path = PINELABS_CANCEL_PATH
			self.default_pos_device_id = None
			self.pos_timeout_seconds = 30
			self.pos_mode_of_payment = "Pine Labs POS"

	def set_pinelabs_pos_base_url(self):
		default_url = PINELABS_PRODUCTION_BASE_URL if self.pinelabs_pos_mode == "Live" else PINELABS_BASE_URL
		current_url = (self.pinelabs_base_url or "").rstrip("/")
		if not current_url:
			self.pinelabs_base_url = default_url
			return
		if self.pinelabs_pos_mode == "Live" and current_url == PINELABS_BASE_URL:
			self.pinelabs_base_url = PINELABS_PRODUCTION_BASE_URL
			return
		if self.pinelabs_pos_mode != "Live" and current_url == PINELABS_PRODUCTION_BASE_URL:
			self.pinelabs_base_url = PINELABS_BASE_URL
			return
		self.pinelabs_base_url = current_url

	def clear_secret(self, fieldname):
		self.set(fieldname, None)
		remove_encrypted_password(self.doctype, self.name or self.doctype, fieldname)



def ensure_single():
	if frappe.db.exists("DocType", "Payment Orchestrator Settings") and not frappe.db.exists("Payment Orchestrator Settings", "Payment Orchestrator Settings"):
		doc = frappe.get_doc({"doctype": "Payment Orchestrator Settings"})
		doc.insert(ignore_permissions=True)
