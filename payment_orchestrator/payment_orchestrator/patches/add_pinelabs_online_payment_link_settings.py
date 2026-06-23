import frappe


def execute():
    frappe.reload_doc("payment_orchestrator", "doctype", "payment_orchestrator_settings")
    defaults = {
        "pinelabs_online_base_url": "https://pluraluat.v2.pinepg.in",
        "pinelabs_online_auth_path": "/api/auth/v1/token",
        "pinelabs_payment_link_path": "/api/pay/v1/paymentlink",
        "pinelabs_payment_link_allowed_methods": "CARD,UPI",
    }
    for fieldname, value in defaults.items():
        if not frappe.db.get_single_value("Payment Orchestrator Settings", fieldname):
            frappe.db.set_single_value("Payment Orchestrator Settings", fieldname, value)
