import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from payment_orchestrator.setup.install import (
    _reference_summary_fields_for_install,
    sync_reference_field_placement,
    sync_reference_field_visibility,
)


def execute():
    create_custom_fields(_reference_summary_fields_for_install(), update=True)
    sync_reference_field_placement()
    sync_reference_field_visibility()
    frappe.db.commit()
