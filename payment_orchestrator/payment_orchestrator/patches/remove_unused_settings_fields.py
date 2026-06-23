import frappe


UNUSED_FIELDS = (
    "provider_mode",
    "provider_name",
    "payment_gateway_label",
    "pos_api_base_url",
    "pos_create_request_path",
    "pos_fetch_request_path",
    "enable_order_checkout",
    "enable_settlement_sync",
    "payment_link_reminder_hours",
    "allow_manual_regenerate_payment_link",
    "show_provider_debug_info",
    "mask_provider_payloads_in_ui",
)


def execute():
    frappe.reload_doc("payment_orchestrator", "doctype", "payment_orchestrator_settings")
    frappe.db.delete(
        "Singles",
        {
            "doctype": "Payment Orchestrator Settings",
            "field": ("in", UNUSED_FIELDS),
        },
    )
