import frappe


def execute():
    frappe.reload_doc("payment_orchestrator", "doctype", "payment_orchestrator_settings")
    meta = frappe.get_meta("Payment Orchestrator Settings")
    provider_mode = "Test"
    if meta.has_field("provider_mode"):
        provider_mode = frappe.db.get_single_value("Payment Orchestrator Settings", "provider_mode") or "Test"
    defaults = {
        "razorpay_payment_link_mode": provider_mode,
        "razorpay_pos_mode": provider_mode,
        "pinelabs_pos_mode": provider_mode,
        "pinelabs_payment_link_mode": provider_mode,
    }
    for fieldname, value in defaults.items():
        if not frappe.db.get_single_value("Payment Orchestrator Settings", fieldname):
            frappe.db.set_single_value("Payment Orchestrator Settings", fieldname, value)
