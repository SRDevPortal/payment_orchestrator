import frappe


def execute():
    if not frappe.db.exists("DocType", "Payment Orchestrator Settings"):
        return

    defaults = {
        "enable_razorpay": 1,
        "enable_razorpay_payment_link": 1,
        "enable_razorpay_pos": 0,
        "enable_razorpay_webhook_processing": 1,
        "enable_pinelabs": 1,
        "enable_pinelabs_payment_link": 0,
        "enable_pinelabs_pos": 1,
        "enable_pinelabs_postback_processing": 1,
        "enable_on_crm_lead": 1,
        "crm_lead_default_request_type": "Advance",
        "crm_lead_allow_partial_payment": 1,
        "crm_lead_auto_create_customer": 1,
    }

    for fieldname, value in defaults.items():
        frappe.db.set_single_value("Payment Orchestrator Settings", fieldname, value)
