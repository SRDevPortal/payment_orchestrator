import frappe

from payment_orchestrator.utils import (
	REQUIRED_MODES_OF_PAYMENT,
	get_flag,
	get_public_webhook_url,
	get_settings,
	mode_of_payment_account,
)


@frappe.whitelist()
def get_setup_status():
	frappe.only_for(("System Manager",))
	settings = get_settings()
	return {
		"settings_name": settings.name,
		"provider_enabled": get_flag(settings, "provider_enabled"),
		"company": settings.company,
		"default_currency": settings.default_currency,
		"default_mode_of_payment": settings.default_mode_of_payment,
		"enable_razorpay": get_flag(settings, "enable_razorpay", 1),
		"enable_razorpay_payment_link": get_flag(settings, "enable_razorpay_payment_link", 1),
		"razorpay_payment_link_mode": getattr(settings, "razorpay_payment_link_mode", None),
		"enable_razorpay_pos": get_flag(settings, "enable_razorpay_pos"),
		"razorpay_pos_mode": getattr(settings, "razorpay_pos_mode", None),
		"enable_razorpay_webhook_processing": get_flag(settings, "enable_razorpay_webhook_processing", 1),
		"enable_pinelabs": get_flag(settings, "enable_pinelabs", 1),
		"enable_pinelabs_payment_link": get_flag(settings, "enable_pinelabs_payment_link"),
		"pinelabs_payment_link_mode": getattr(settings, "pinelabs_payment_link_mode", None),
		"enable_pinelabs_pos": get_flag(settings, "enable_pinelabs_pos", 1),
		"pinelabs_pos_mode": getattr(settings, "pinelabs_pos_mode", None),
		"enable_pinelabs_postback_processing": get_flag(settings, "enable_pinelabs_postback_processing", 1),
		"enable_pos_payments": get_flag(settings, "enable_pos_payments"),
		"default_pos_device_id": settings.default_pos_device_id,
		"pinelabs_merchant_id": settings.pinelabs_merchant_id,
		"pinelabs_merchant_name": getattr(settings, "pinelabs_merchant_name", None),
		"pinelabs_store_id": settings.pinelabs_store_id,
		"pinelabs_store_name": getattr(settings, "pinelabs_store_name", None),
		"pinelabs_client_id": settings.pinelabs_client_id,
		"pinelabs_device_no": getattr(settings, "pinelabs_device_no", None),
		"has_pinelabs_security_token": bool(settings.get_password("pinelabs_security_token", raise_exception=False)),
		"pinelabs_base_url": getattr(settings, "pinelabs_base_url", None),
		"pinelabs_online_base_url": getattr(settings, "pinelabs_online_base_url", None),
		"pinelabs_payment_link_path": getattr(settings, "pinelabs_payment_link_path", None),
		"has_pinelabs_online_client_id": bool(getattr(settings, "pinelabs_online_client_id", None)),
		"has_pinelabs_online_client_secret": bool(settings.get_password("pinelabs_online_client_secret", raise_exception=False)),
		"webhook_url": get_public_webhook_url(),
		"pinelabs_postback_url": get_public_webhook_url('/api/method/payment_orchestrator.api.webhooks.pinelabs'),
		"has_key_id": bool(settings.key_id),
		"has_key_secret": bool(settings.get_password("key_secret", raise_exception=False)),
		"has_webhook_secret": bool(settings.get_password("webhook_secret", raise_exception=False)),
		"enable_on_crm_lead": get_flag(settings, "enable_on_crm_lead", 1),
		"enable_on_patient_encounter": settings.enable_on_patient_encounter,
		"encounter_status_after_payment": getattr(settings, "encounter_status_after_payment", None),
		"enable_on_sales_order": settings.enable_on_sales_order,
		"enable_on_sales_invoice": settings.enable_on_sales_invoice,
		"modes_of_payment": get_mode_of_payment_statuses(settings.company),
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
	razorpay_webhooks_enabled = (
		get_flag(settings, "enable_razorpay", 1)
		and get_flag(settings, "enable_webhook_processing", 1)
		and get_flag(settings, "enable_razorpay_webhook_processing", 1)
	)
	pinelabs_pos_enabled = get_flag(settings, "enable_pinelabs", 1) and get_flag(settings, "enable_pinelabs_pos", 1)

	checks.append({
		"name": "settings-single",
		"ok": bool(settings.name),
		"message": f"Settings record: {settings.name}",
	})
	checks.append({
		"name": "razorpay-payment-link-mode",
		"ok": True,
		"message": "Razorpay Payment Link enabled" if get_flag(settings, "enable_razorpay", 1) and get_flag(settings, "enable_razorpay_payment_link", 1) else "Razorpay Payment Link disabled",
	})
	checks.append({
		"name": "pinelabs-pos-mode",
		"ok": True,
		"message": "Pine Labs POS enabled" if get_flag(settings, "enable_pinelabs", 1) and get_flag(settings, "enable_pinelabs_pos", 1) else "Pine Labs POS disabled",
	})
	checks.append({
		"name": "pinelabs-payment-link-mode",
		"ok": True,
		"message": "Pine Labs Payment Link enabled" if get_flag(settings, "enable_pinelabs", 1) and get_flag(settings, "enable_pinelabs_payment_link") else "Pine Labs Payment Link disabled",
	})
	checks.append({
		"name": "pinelabs-merchant-id",
		"ok": True if not pinelabs_pos_enabled else bool(settings.pinelabs_merchant_id),
		"message": "Pine Labs POS disabled" if not pinelabs_pos_enabled else ("Pine Labs Merchant ID present" if settings.pinelabs_merchant_id else "Pine Labs Merchant ID missing"),
	})
	checks.append({
		"name": "pinelabs-security-token",
		"ok": True if not pinelabs_pos_enabled else bool(settings.get_password("pinelabs_security_token", raise_exception=False)),
		"message": "Pine Labs POS disabled" if not pinelabs_pos_enabled else ("Pine Labs Security Token present" if settings.get_password("pinelabs_security_token", raise_exception=False) else "Pine Labs Security Token missing"),
	})
	checks.append({
		"name": "webhook-secret",
		"ok": True if not razorpay_webhooks_enabled else bool(settings.get_password("webhook_secret", raise_exception=False)),
		"message": "Razorpay webhook disabled" if not razorpay_webhooks_enabled else ("Webhook secret present" if settings.get_password("webhook_secret", raise_exception=False) else "Webhook secret missing"),
	})
	checks.append({
		"name": "webhook-url",
		"ok": bool(get_public_webhook_url()),
		"message": get_public_webhook_url(),
	})
	checks.append({
		"name": "pinelabs-postback-url",
		"ok": bool(get_public_webhook_url('/api/method/payment_orchestrator.api.webhooks.pinelabs')),
		"message": get_public_webhook_url('/api/method/payment_orchestrator.api.webhooks.pinelabs'),
	})

	for row in get_mode_of_payment_statuses(settings.company):
		checks.append({
			"name": f"mode-of-payment:{row['mode']}",
			"ok": row["exists"],
			"message": f"{row['mode']} exists" if row["exists"] else f"{row['mode']} missing",
		})
		checks.append({
			"name": f"mode-of-payment-account:{row['mode']}",
			"ok": True,
			"message": (
				f"{row['mode']} mapped to {row['account']}"
				if row["account_mapped"]
				else f"{row['mode']} has no account mapping for {settings.company or 'company'}"
			),
		})

	for doctype in ["CRM Lead", "Patient Encounter", "Sales Order", "Sales Invoice"]:
		exists = bool(frappe.db.exists("DocType", doctype))
		checks.append({
			"name": f"doctype-exists:{doctype}",
			"ok": exists,
			"message": f"{doctype} available" if exists else f"{doctype} missing on site",
		})

	return {
		"ok": all(item["ok"] for item in checks if not item["name"].startswith("doctype-exists:Patient Encounter")),
		"checks": checks,
	}


def get_mode_of_payment_statuses(company=None):
	rows = []
	for mode in REQUIRED_MODES_OF_PAYMENT:
		exists = bool(frappe.db.exists("Mode of Payment", mode))
		account = mode_of_payment_account(company, mode) if exists and company else None
		rows.append({
			"mode": mode,
			"exists": exists,
			"account": account,
			"account_mapped": bool(account),
		})
	return rows
