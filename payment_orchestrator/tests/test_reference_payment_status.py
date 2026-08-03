from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from payment_orchestrator.patches import add_reference_payment_status
from payment_orchestrator.services import derive_reference_payment_status
from payment_orchestrator.setup.install import REFERENCE_SUMMARY_FIELDS


class ReferencePaymentStatusTests(TestCase):
    def status(self, latest=None, **summary):
        values = {
            'total_paid': 0,
            'total_refunded': 0,
            'total_allocated': 0,
            'total_unallocated': 0,
            **summary,
        }
        return derive_reference_payment_status(values, latest)

    def test_no_payment_request(self):
        self.assertEqual(self.status(), 'Not Requested')

    def test_awaiting_payment(self):
        latest = SimpleNamespace(status='Requested', payment_status='created')
        self.assertEqual(self.status(latest), 'Awaiting Payment')

    def test_partial_payment_received(self):
        latest = SimpleNamespace(amount_requested=100, amount_paid=40)
        self.assertEqual(self.status(latest, total_paid=40, total_unallocated=40), 'Partially Received')

    def test_payment_received_and_unallocated(self):
        latest = SimpleNamespace(amount_requested=100, amount_paid=100)
        self.assertEqual(self.status(latest, total_paid=100, total_unallocated=100), 'Payment Received')

    def test_partially_allocated(self):
        self.assertEqual(
            self.status(total_paid=100, total_allocated=40, total_unallocated=60),
            'Partially Allocated',
        )

    def test_fully_allocated(self):
        self.assertEqual(
            self.status(total_paid=100, total_allocated=100, total_unallocated=0),
            'Allocated',
        )

    def test_partial_refund_takes_precedence_over_allocation(self):
        self.assertEqual(
            self.status(total_paid=60, total_refunded=40, total_allocated=60, total_unallocated=0),
            'Partially Refunded',
        )

    def test_full_refund(self):
        self.assertEqual(self.status(total_paid=0, total_refunded=100), 'Refunded')

    def test_failed_payment(self):
        latest = SimpleNamespace(status='Requested', payment_status='failed')
        self.assertEqual(self.status(latest), 'Payment Failed')

    def test_expired_payment(self):
        latest = SimpleNamespace(status='Expired', payment_status='closed')
        self.assertEqual(self.status(latest), 'Expired')

    def test_cancelled_payment(self):
        latest = SimpleNamespace(status='Cancelled', payment_status='cancelled')
        self.assertEqual(self.status(latest), 'Cancelled')


class ReferencePaymentStatusFieldTests(TestCase):
    def test_payment_status_field_is_available_on_every_reference_doctype(self):
        self.assertEqual(
            set(REFERENCE_SUMMARY_FIELDS),
            {'CRM Lead', 'Patient Encounter', 'Sales Order', 'Sales Invoice'},
        )

        for doctype, fields in REFERENCE_SUMMARY_FIELDS.items():
            status_field = next(
                (field for field in fields if field.get('fieldname') == 'po_payment_status'),
                None,
            )
            with self.subTest(doctype=doctype):
                self.assertIsNotNone(status_field)
                self.assertEqual(status_field.get('label'), 'Payment Status')
                self.assertIsNone(status_field.get('default'))
                self.assertEqual(status_field.get('in_list_view'), 1)
                self.assertEqual(status_field.get('in_standard_filter'), 0)
                self.assertEqual(status_field.get('search_index'), 0)


class ReferencePaymentStatusBackfillTests(TestCase):
    def test_backfill_only_updates_existing_payment_intent_references_in_batches(self):
        fake_frappe = MagicMock()
        fake_frappe.db.exists.return_value = True
        fake_frappe.db.has_column.return_value = True
        payment_references = [f'ENC-{index}' for index in range(501)]

        with (
            patch.object(add_reference_payment_status, 'frappe', fake_frappe),
            patch.object(add_reference_payment_status, 'REFERENCE_SUMMARY_FIELDS', {'Patient Encounter': []}),
            patch.object(add_reference_payment_status, 'create_custom_fields'),
            patch.object(add_reference_payment_status, '_reference_summary_fields_for_install', return_value={}),
            patch.object(add_reference_payment_status, 'sync_reference_field_placement'),
            patch.object(add_reference_payment_status, 'sync_reference_field_visibility'),
            patch.object(
                add_reference_payment_status,
                '_payment_reference_names',
                return_value=payment_references,
            ),
            patch.object(
                add_reference_payment_status,
                '_existing_reference_names',
                side_effect=lambda doctype, names: names[:1],
            ) as existing_references,
            patch.object(
                add_reference_payment_status,
                'update_reference_payment_summary',
            ) as update_summary,
        ):
            add_reference_payment_status.execute()

        self.assertEqual(existing_references.call_count, 2)
        self.assertEqual(len(existing_references.call_args_list[0].args[1]), 500)
        self.assertEqual(len(existing_references.call_args_list[1].args[1]), 1)
        update_summary.assert_any_call('Patient Encounter', 'ENC-0')
        update_summary.assert_any_call('Patient Encounter', 'ENC-500')
        self.assertEqual(update_summary.call_count, 2)
        fake_frappe.db.sql.assert_not_called()

    def test_missing_payment_status_column_skips_backfill(self):
        fake_frappe = MagicMock()
        fake_frappe.db.exists.return_value = True
        fake_frappe.db.has_column.return_value = False

        with (
            patch.object(add_reference_payment_status, 'frappe', fake_frappe),
            patch.object(add_reference_payment_status, 'REFERENCE_SUMMARY_FIELDS', {'Patient Encounter': []}),
            patch.object(add_reference_payment_status, 'create_custom_fields'),
            patch.object(add_reference_payment_status, '_reference_summary_fields_for_install', return_value={}),
            patch.object(add_reference_payment_status, 'sync_reference_field_placement'),
            patch.object(add_reference_payment_status, 'sync_reference_field_visibility'),
            patch.object(add_reference_payment_status, '_payment_reference_names') as payment_references,
            patch.object(add_reference_payment_status, 'update_reference_payment_summary') as update_summary,
        ):
            add_reference_payment_status.execute()

        payment_references.assert_not_called()
        update_summary.assert_not_called()

    def test_no_payment_intent_references_skips_document_lookup_and_updates(self):
        fake_frappe = MagicMock()
        fake_frappe.db.exists.return_value = True
        fake_frappe.db.has_column.return_value = True

        with (
            patch.object(add_reference_payment_status, 'frappe', fake_frappe),
            patch.object(add_reference_payment_status, 'REFERENCE_SUMMARY_FIELDS', {'Patient Encounter': []}),
            patch.object(add_reference_payment_status, 'create_custom_fields'),
            patch.object(add_reference_payment_status, '_reference_summary_fields_for_install', return_value={}),
            patch.object(add_reference_payment_status, 'sync_reference_field_placement'),
            patch.object(add_reference_payment_status, 'sync_reference_field_visibility'),
            patch.object(add_reference_payment_status, '_payment_reference_names', return_value=[]),
            patch.object(add_reference_payment_status, '_existing_reference_names') as existing_references,
            patch.object(add_reference_payment_status, 'update_reference_payment_summary') as update_summary,
        ):
            add_reference_payment_status.execute()

        existing_references.assert_not_called()
        update_summary.assert_not_called()

    def test_reference_lookup_uses_payment_intent_and_indexed_document_names_only(self):
        fake_frappe = MagicMock()
        fake_frappe.db.sql.return_value = ['ENC-PAID-1', 'ENC-PAID-2']
        fake_frappe.get_all.return_value = ['ENC-PAID-1']

        with patch.object(add_reference_payment_status, 'frappe', fake_frappe):
            payment_references = add_reference_payment_status._payment_reference_names('Patient Encounter')
            existing_references = add_reference_payment_status._existing_reference_names(
                'Patient Encounter',
                payment_references,
            )

        payment_query = fake_frappe.db.sql.call_args.args[0]
        self.assertIn('tabPayment Intent', payment_query)
        self.assertNotIn('tabPatient Encounter', payment_query)
        fake_frappe.get_all.assert_called_once_with(
            'Patient Encounter',
            filters={'name': ['in', ['ENC-PAID-1', 'ENC-PAID-2']]},
            pluck='name',
            limit_page_length=0,
        )
        self.assertEqual(existing_references, ['ENC-PAID-1'])

    def test_sales_invoice_backfill_includes_direct_and_linked_references(self):
        fake_frappe = MagicMock()
        fake_frappe.db.sql.side_effect = [
            ['SINV-1'],
            ['SINV-2', 'SINV-1'],
        ]

        with patch.object(add_reference_payment_status, 'frappe', fake_frappe):
            references = add_reference_payment_status._payment_reference_names('Sales Invoice')

        self.assertEqual(references, ['SINV-1', 'SINV-2'])
