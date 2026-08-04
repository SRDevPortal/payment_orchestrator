import frappe

from payment_orchestrator.setup.install import REFERENCE_SUMMARY_FIELDS


def execute():
    for doctype, fields in REFERENCE_SUMMARY_FIELDS.items():
        if not frappe.db.exists('DocType', doctype):
            continue

        for field in fields:
            if not field.get('allow_on_submit'):
                continue
            custom_field = f"{doctype}-{field['fieldname']}"
            if frappe.db.exists('Custom Field', custom_field):
                frappe.db.set_value(
                    'Custom Field',
                    custom_field,
                    'allow_on_submit',
                    1,
                    update_modified=False,
                )

        frappe.clear_cache(doctype=doctype)

    frappe.db.commit()
