import frappe


def execute():
    if not frappe.db.exists("DocType", "Payment Intent"):
        return

    frappe.reload_doc("payment_orchestrator", "doctype", "payment_intent")

    frappe.db.sql(
        """
        update `tabPayment Intent`
        set gateway = case
            when request_channel = 'POS' then 'Pine Labs'
            when provider in ('Pine Labs', 'Pinelabs') then 'Pine Labs'
            else 'Razorpay'
        end
        where coalesce(gateway, '') = ''
        """
    )

    frappe.db.sql(
        """
        update `tabPayment Intent`
        set payment_mode = case
            when request_channel = 'POS' then 'POS'
            when request_channel in ('Checkout', 'Manual Share') then request_channel
            else 'Payment Link'
        end
        where coalesce(payment_mode, '') = ''
        """
    )
