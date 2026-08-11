import frappe
from frappe.tests import IntegrationTestCase

from payment_orchestrator.api.webhooks import _insert_provider_event
from payment_orchestrator.setup.install import setup_all


class PaymentOrchestratorFrappe16MigrationTests(IntegrationTestCase):
    def test_duplicate_guard_key_is_unique(self):
        field = frappe.get_meta("Payment Provider Event").get_field("duplicate_guard_key")
        self.assertEqual(field.unique, 1)

    def test_duplicate_webhook_returns_existing_event(self):
        guard_key = frappe.generate_hash(length=32)
        values = {
            "doctype": "Payment Provider Event",
            "provider": "Frappe 16 Test",
            "duplicate_guard_key": guard_key,
        }

        first_event, first_is_duplicate = _insert_provider_event(values)
        duplicate_event, second_is_duplicate = _insert_provider_event(values)

        self.assertFalse(first_is_duplicate)
        self.assertTrue(second_is_duplicate)
        self.assertEqual(duplicate_event.name, first_event.name)

    def test_setup_is_idempotent(self):
        setup_all()
        setup_all()

        self.assertTrue(frappe.db.exists("Payment Orchestrator Settings"))
        for doctype in ("CRM Lead", "Patient Encounter", "Sales Order", "Sales Invoice"):
            self.assertTrue(frappe.db.exists("Custom Field", f"{doctype}-po_payment_tab"))
