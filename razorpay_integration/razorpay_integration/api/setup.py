import frappe

from razorpay_integration.utils import get_public_webhook_url, get_settings


@frappe.whitelist()
def get_setup_status():
	frappe.only_for(("System Manager",))
	settings = get_settings()
	return {
		"settings_name": settings.name,
		"provider_enabled": settings.provider_enabled,
		"provider_name": settings.provider_name,
		"provider_mode": settings.provider_mode,
		"company": settings.company,
		"default_currency": settings.default_currency,
		"default_mode_of_payment": settings.default_mode_of_payment,
		"enable_pos_payments": settings.enable_pos_payments,
		"default_pos_device_id": settings.default_pos_device_id,
		"pos_create_request_path": settings.pos_create_request_path,
		"pinelabs_merchant_id": settings.pinelabs_merchant_id,
		"pinelabs_store_id": settings.pinelabs_store_id,
		"pinelabs_client_id": settings.pinelabs_client_id,
		"has_pinelabs_security_token": bool(settings.get_password("pinelabs_security_token", raise_exception=False)),
		"webhook_url": get_public_webhook_url(),
		"pinelabs_postback_url": get_public_webhook_url('/api/method/razorpay_integration.api.webhooks.pinelabs'),
		"has_key_id": bool(settings.key_id),
		"has_key_secret": bool(settings.get_password("key_secret", raise_exception=False)),
		"has_webhook_secret": bool(settings.get_password("webhook_secret", raise_exception=False)),
		"enable_on_lead": settings.enable_on_lead,
		"enable_on_patient_encounter": settings.enable_on_patient_encounter,
		"enable_on_sales_order": settings.enable_on_sales_order,
		"enable_on_sales_invoice": settings.enable_on_sales_invoice,
		"counts": {
			"payment_intents": frappe.db.count("Payment Intent"),
			"payment_allocations": frappe.db.count("Payment Allocation"),
			"provider_events": frappe.db.count("Payment Provider Event"),
		},
	}


@frappe.whitelist()
def smoke_check():
	frappe.only_for(("System Manager",))
	settings = get_settings()
	checks = []

	checks.append({
		"name": "settings-single",
		"ok": bool(settings.name),
		"message": f"Settings record: {settings.name}",
	})
	checks.append({
		"name": "provider-name",
		"ok": (settings.provider_name or "") == "Pine Labs",
		"message": f"Provider: {settings.provider_name or '-'}",
	})
	checks.append({
		"name": "pinelabs-merchant-id",
		"ok": bool(settings.pinelabs_merchant_id),
		"message": "Pine Labs Merchant ID present" if settings.pinelabs_merchant_id else "Pine Labs Merchant ID missing",
	})
	checks.append({
		"name": "pinelabs-security-token",
		"ok": bool(settings.get_password("pinelabs_security_token", raise_exception=False)),
		"message": "Pine Labs Security Token present" if settings.get_password("pinelabs_security_token", raise_exception=False) else "Pine Labs Security Token missing",
	})
	checks.append({
		"name": "webhook-secret",
		"ok": bool(settings.get_password("webhook_secret", raise_exception=False)),
		"message": "Webhook secret present" if settings.get_password("webhook_secret", raise_exception=False) else "Webhook secret missing",
	})
	checks.append({
		"name": "webhook-url",
		"ok": bool(get_public_webhook_url()),
		"message": get_public_webhook_url(),
	})
	checks.append({
		"name": "pinelabs-postback-url",
		"ok": bool(get_public_webhook_url('/api/method/razorpay_integration.api.webhooks.pinelabs')),
		"message": get_public_webhook_url('/api/method/razorpay_integration.api.webhooks.pinelabs'),
	})

	for doctype in ["Lead", "Patient Encounter", "Sales Order", "Sales Invoice"]:
		checks.append({
			"name": f"doctype-exists:{doctype}",
			"ok": frappe.db.exists("DocType", doctype),
			"message": f"{doctype} available" if frappe.db.exists("DocType", doctype) else f"{doctype} missing on site",
		})

	return {
		"ok": all(item["ok"] for item in checks if not item["name"].startswith("doctype-exists:Patient Encounter")),
		"checks": checks,
	}
