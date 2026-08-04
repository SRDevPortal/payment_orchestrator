from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch

from payment_orchestrator.api import allocations
from payment_orchestrator.patches import (
    add_reference_payment_status,
    allow_payment_summary_after_submit,
    hide_empty_payment_summary,
)
from payment_orchestrator.services import derive_reference_payment_status
from payment_orchestrator.setup.install import PAYMENT_SUMMARY_DEPENDS_ON, REFERENCE_SUMMARY_FIELDS


class FakeReferenceDoc:
    def __init__(self, doctype='Patient Encounter', name='HLC-ENC-TEST', **values):
        self.doctype = doctype
        self.name = name
        for fieldname, value in values.items():
            setattr(self, fieldname, value)

    def get(self, fieldname, default=None):
        return getattr(self, fieldname, default)

    def set(self, fieldname, value):
        setattr(self, fieldname, value)


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

    def test_all_computed_summary_fields_allow_updates_after_submit(self):
        computed_fields = {
            'po_total_requested',
            'po_total_paid',
            'po_total_allocated',
            'po_total_unallocated',
            'po_payment_status',
            'po_last_payment_intent',
        }

        for doctype, fields in REFERENCE_SUMMARY_FIELDS.items():
            fields_by_name = {field['fieldname']: field for field in fields}
            for fieldname in computed_fields:
                with self.subTest(doctype=doctype, fieldname=fieldname):
                    self.assertEqual(fields_by_name[fieldname].get('read_only'), 1)
                    self.assertEqual(fields_by_name[fieldname].get('allow_on_submit'), 1)

    def test_payment_summary_tab_depends_on_payment_history_for_every_reference_doctype(self):
        for doctype, fields in REFERENCE_SUMMARY_FIELDS.items():
            payment_tab = next(
                (field for field in fields if field.get('fieldname') == 'po_payment_tab'),
                None,
            )
            with self.subTest(doctype=doctype):
                self.assertIsNotNone(payment_tab)
                self.assertEqual(payment_tab.get('depends_on'), PAYMENT_SUMMARY_DEPENDS_ON)


class EmptyPaymentSummaryPatchTests(TestCase):
    def test_patch_only_updates_custom_field_metadata_and_payment_intent_indexes(self):
        fake_frappe = MagicMock()
        fake_frappe.db.exists.return_value = True
        fake_frappe.db.has_column.return_value = True

        with (
            patch.object(hide_empty_payment_summary, 'frappe', fake_frappe),
            patch.object(
                hide_empty_payment_summary,
                'REFERENCE_SUMMARY_FIELDS',
                {'Patient Encounter': []},
            ),
        ):
            hide_empty_payment_summary.execute()

        fake_frappe.db.set_value.assert_called_once_with(
            'Custom Field',
            'Patient Encounter-po_payment_tab',
            'depends_on',
            PAYMENT_SUMMARY_DEPENDS_ON,
            update_modified=False,
        )
        fake_frappe.db.add_index.assert_any_call(
            'Payment Intent',
            ['reference_doctype', 'reference_name'],
            index_name='payment_intent_reference_index',
        )
        fake_frappe.db.add_index.assert_any_call(
            'Payment Intent',
            ['sales_invoice'],
            index_name='payment_intent_sales_invoice_index',
        )
        self.assertEqual(fake_frappe.db.add_index.call_count, 2)


class PaymentSummaryAfterSubmitPatchTests(TestCase):
    def test_patch_updates_only_computed_custom_field_metadata(self):
        fake_frappe = MagicMock()
        fake_frappe.db.exists.return_value = True

        with patch.object(allow_payment_summary_after_submit, 'frappe', fake_frappe):
            allow_payment_summary_after_submit.execute()

        self.assertEqual(fake_frappe.db.set_value.call_count, 24)
        for call in fake_frappe.db.set_value.call_args_list:
            self.assertEqual(call.args[0], 'Custom Field')
            self.assertIn(call.args[1].split('-', 1)[-1], {
                'po_total_requested',
                'po_total_paid',
                'po_total_allocated',
                'po_total_unallocated',
                'po_payment_status',
                'po_last_payment_intent',
            })
            self.assertEqual(call.args[2:], ('allow_on_submit', 1))
            self.assertFalse(call.kwargs['update_modified'])
        fake_frappe.db.sql.assert_not_called()
        fake_frappe.get_all.assert_not_called()


class ReferenceSummaryHookTests(TestCase):
    def test_direct_sync_without_intent_skips_database_write(self):
        with (
            patch.object(allocations, 'is_doctype_enabled', return_value=True),
            patch(
                'payment_orchestrator.services.reference_has_payment_intents',
                return_value=False,
            ) as has_intents,
            patch('payment_orchestrator.services.update_reference_payment_summary') as update_summary,
        ):
            result = allocations.sync_reference_summary('Sales Invoice', 'SINV-NO-PAYMENT')

        self.assertIsNone(result)
        has_intents.assert_called_once_with('Sales Invoice', 'SINV-NO-PAYMENT')
        update_summary.assert_not_called()

    def test_no_intent_and_no_summary_state_skips_database_write(self):
        doc = FakeReferenceDoc(po_payment_status=None)

        with (
            patch.object(allocations, 'is_doctype_enabled', return_value=True),
            patch(
                'payment_orchestrator.services.reference_has_payment_intents',
                return_value=False,
            ) as has_intents,
            patch('payment_orchestrator.services.update_reference_payment_summary') as update_summary,
        ):
            result = allocations.sync_reference_summary(doc)

        self.assertIsNone(result)
        has_intents.assert_called_once_with('Patient Encounter', 'HLC-ENC-TEST')
        update_summary.assert_not_called()
        self.assertIsNone(doc.po_payment_status)

    def test_existing_intent_updates_database_and_returned_document(self):
        doc = FakeReferenceDoc(po_payment_status=None)
        summary = {
            'po_total_requested': 100,
            'po_total_paid': 100,
            'po_total_allocated': 0,
            'po_total_unallocated': 100,
            'po_payment_status': 'Payment Received',
            'po_last_payment_intent': 'PI-0001',
        }

        with (
            patch.object(allocations, 'is_doctype_enabled', return_value=True),
            patch(
                'payment_orchestrator.services.reference_has_payment_intents',
                return_value=True,
            ),
            patch(
                'payment_orchestrator.services.update_reference_payment_summary',
                return_value=summary,
            ) as update_summary,
        ):
            result = allocations.sync_reference_summary(doc)

        self.assertEqual(result, summary)
        update_summary.assert_called_once_with('Patient Encounter', 'HLC-ENC-TEST')
        for fieldname, value in summary.items():
            self.assertEqual(doc.get(fieldname), value)

    def test_stale_summary_is_cleared_and_mirrored_without_existence_lookup(self):
        doc = FakeReferenceDoc(
            po_total_requested=100,
            po_payment_status='Awaiting Payment',
            po_last_payment_intent='PI-DELETED',
        )
        cleared_summary = {
            'po_total_requested': 0,
            'po_total_paid': 0,
            'po_total_allocated': 0,
            'po_total_unallocated': 0,
            'po_payment_status': 'Not Requested',
            'po_last_payment_intent': None,
        }

        with (
            patch.object(allocations, 'is_doctype_enabled', return_value=True),
            patch('payment_orchestrator.services.reference_has_payment_intents') as has_intents,
            patch(
                'payment_orchestrator.services.update_reference_payment_summary',
                return_value=cleared_summary,
            ),
        ):
            allocations.sync_reference_summary(doc)

        has_intents.assert_not_called()
        self.assertEqual(doc.po_payment_status, 'Not Requested')
        self.assertIsNone(doc.po_last_payment_intent)
        self.assertEqual(doc.po_total_requested, 0)


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
