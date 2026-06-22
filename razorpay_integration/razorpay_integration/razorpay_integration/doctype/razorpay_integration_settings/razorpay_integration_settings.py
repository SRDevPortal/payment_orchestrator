import frappe
from frappe.model.document import Document

class RazorpayIntegrationSettings(Document):
	def validate(self):
		self.provider_name = self.provider_name or "Pine Labs"
		if not self.api_base_url or "api.razorpay_integration.com" in self.api_base_url:
			self.api_base_url = "https://api.razorpay.com/v1"
		self.api_base_url = self.api_base_url.rstrip("/")
		self.default_currency = self.default_currency or "INR"
		self.default_request_channel = self.default_request_channel or "Payment Link"
		self.default_mode_of_payment = self.default_mode_of_payment or "Razorpay"
		self.pos_create_request_path = self.pos_create_request_path or "/pos/payment_requests"
		self.pos_fetch_request_path = self.pos_fetch_request_path or "/pos/payment_requests/{request_id}"
		self.pos_timeout_seconds = max(int(self.pos_timeout_seconds or 30), 1)
		self.pos_mode_of_payment = self.pos_mode_of_payment or "Pine Labs POS"
		if self.default_pos_device_id:
			self.pinelabs_client_id = self.default_pos_device_id
		elif self.pinelabs_client_id:
			self.default_pos_device_id = self.pinelabs_client_id
		self.pinelabs_base_url = (self.pinelabs_base_url or "https://www.plutuscloudserviceuat.in:8201").rstrip("/")
		self.pinelabs_upload_path = self.pinelabs_upload_path or "/API/CloudBasedIntegration/V1/UploadBilledTransaction"
		self.pinelabs_status_path = self.pinelabs_status_path or "/API/CloudBasedIntegration/V1/GetCloudBasedTxnStatus"
		self.pinelabs_cancel_path = self.pinelabs_cancel_path or "/API/CloudBasedIntegration/V1/CancelTransaction"
		self.pinelabs_allowed_payment_mode = self.pinelabs_allowed_payment_mode or "0"
		self.pinelabs_auto_cancel_duration = max(int(self.pinelabs_auto_cancel_duration or 5), 1)
		self.payment_link_expiry_hours = max(int(self.payment_link_expiry_hours or 72), 1)
		self.payment_link_reminder_hours = max(int(self.payment_link_reminder_hours or 24), 1)

		if self.provider_enabled and not self.key_id:
			frappe.msgprint("Payment provider is enabled but API Key ID is empty.")



def ensure_single():
	if frappe.db.exists("DocType", "Razorpay Integration Settings") and not frappe.db.exists("Razorpay Integration Settings", "Razorpay Integration Settings"):
		doc = frappe.get_doc({"doctype": "Razorpay Integration Settings"})
		doc.insert(ignore_permissions=True)
