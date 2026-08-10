import frappe

from payment_orchestrator.setup.install import (
    PAYMENT_SUMMARY_DEPENDS_ON,
    REFERENCE_SUMMARY_FIELDS,
)


def execute():
    for doctype in REFERENCE_SUMMARY_FIELDS:
        custom_field = f'{doctype}-po_payment_tab'
        if not frappe.db.exists('Custom Field', custom_field):
            continue
        frappe.db.set_value(
            'Custom Field',
            custom_field,
            'depends_on',
            PAYMENT_SUMMARY_DEPENDS_ON,
            update_modified=False,
        )
        frappe.clear_cache(doctype=doctype)

    if frappe.db.exists('DocType', 'Payment Intent'):
        frappe.db.add_index(
            'Payment Intent',
            ['reference_doctype', 'reference_name'],
            index_name='payment_intent_reference_index',
        )
        if frappe.db.has_column('Payment Intent', 'sales_invoice'):
            frappe.db.add_index(
                'Payment Intent',
                ['sales_invoice'],
                index_name='payment_intent_sales_invoice_index',
            )
