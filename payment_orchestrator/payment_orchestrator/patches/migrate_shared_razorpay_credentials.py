import frappe
from frappe.utils.password import get_decrypted_password, set_encrypted_password


def execute():
    if not frappe.db.exists("DocType", "Payment Orchestrator Settings"):
        return

    doctype = "Payment Orchestrator Settings"
    legacy_key_id = frappe.db.get_single_value(doctype, "key_id")
    legacy_key_secret = get_decrypted_password(doctype, doctype, "key_secret", raise_exception=False)
    if not legacy_key_id and not legacy_key_secret:
        return

    mode = frappe.db.get_single_value(doctype, "razorpay_payment_link_mode") or "Test"
    if mode == "Live":
        key_field = "razorpay_live_key_id"
        secret_field = "razorpay_live_key_secret"
    else:
        key_field = "razorpay_test_key_id"
        secret_field = "razorpay_test_key_secret"

    if legacy_key_id and not frappe.db.get_single_value(doctype, key_field):
        frappe.db.set_single_value(doctype, key_field, legacy_key_id)
    if legacy_key_secret and not get_decrypted_password(doctype, doctype, secret_field, raise_exception=False):
        set_encrypted_password(doctype, doctype, legacy_key_secret, secret_field)
