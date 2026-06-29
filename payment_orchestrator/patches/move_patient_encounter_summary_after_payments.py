import frappe

from payment_orchestrator.setup.install import (
    sync_patient_encounter_field_placement,
    sync_reference_field_visibility,
)


def execute():
    sync_patient_encounter_field_placement()
    sync_reference_field_visibility()
    frappe.db.commit()
