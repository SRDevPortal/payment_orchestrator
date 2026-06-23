import frappe


LEAD_CUSTOM_FIELDS = (
    "po_payment_tab",
    "po_total_requested",
    "po_total_paid",
    "po_total_allocated",
    "po_total_unallocated",
    "po_last_payment_intent",
)


def execute():
    frappe.reload_doc("payment_orchestrator", "doctype", "payment_orchestrator_settings")

    if not frappe.db.exists("DocType", "Lead"):
        return

    for fieldname in LEAD_CUSTOM_FIELDS:
        for name in frappe.get_all(
            "Custom Field",
            filters={"dt": "Lead", "fieldname": fieldname},
            pluck="name",
        ):
            frappe.delete_doc("Custom Field", name, ignore_permissions=True, force=True)
