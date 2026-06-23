import frappe


def execute():
    old_doctype = "Razorpay Integration Settings"
    new_doctype = "Payment Orchestrator Settings"

    if not frappe.db.exists("DocType", old_doctype):
        return

    frappe.db.sql(
        """
        insert into `tabSingles` (doctype, field, value)
        select %s, field, value
        from `tabSingles`
        where doctype = %s
        on duplicate key update value = values(value)
        """,
        (new_doctype, old_doctype),
    )
