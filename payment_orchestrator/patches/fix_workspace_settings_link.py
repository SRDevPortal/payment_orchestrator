import frappe


def execute():
    frappe.db.set_value(
        "Workspace Link",
        {
            "parent": "Payment Orchestrator",
            "link_to": "Razorpay Settings",
        },
        {
            "label": "Payment Orchestrator Settings",
            "link_to": "Payment Orchestrator Settings",
        },
    )
