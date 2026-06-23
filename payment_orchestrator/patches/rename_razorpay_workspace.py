import frappe


def execute():
    if frappe.db.exists("Workspace", "Razorpay"):
        if frappe.db.exists("Workspace", "Payment Orchestrator"):
            frappe.delete_doc("Workspace", "Razorpay", ignore_permissions=True, force=True)
        else:
            frappe.rename_doc(
                "Workspace",
                "Razorpay",
                "Payment Orchestrator",
                force=True,
            )

    if frappe.db.exists("Workspace", "Payment Orchestrator"):
        doc = frappe.get_doc("Workspace", "Payment Orchestrator")
        doc.label = "Payment Orchestrator"
        doc.title = "Payment Orchestrator"
        doc.module = "Payment Orchestrator"
        doc.content = '[{"type": "header", "data": {"text": "Payment Orchestrator", "level": 4}}]'
        doc.save(ignore_permissions=True)
