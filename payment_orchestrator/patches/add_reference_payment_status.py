import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from payment_orchestrator.services import update_reference_payment_summary
from payment_orchestrator.setup.install import (
    REFERENCE_SUMMARY_FIELDS,
    _reference_summary_fields_for_install,
    sync_reference_field_placement,
    sync_reference_field_visibility,
)

BACKFILL_BATCH_SIZE = 500


def execute():
    create_custom_fields(_reference_summary_fields_for_install(), update=True)
    sync_reference_field_placement()
    sync_reference_field_visibility()

    for doctype in REFERENCE_SUMMARY_FIELDS:
        if (
            not frappe.db.exists('DocType', doctype)
            or not frappe.db.has_column(doctype, 'po_payment_status')
        ):
            continue

        reference_names = _payment_reference_names(doctype)
        for reference_batch in _batches(reference_names, BACKFILL_BATCH_SIZE):
            for reference_name in _existing_reference_names(doctype, reference_batch):
                update_reference_payment_summary(doctype, reference_name)
            frappe.db.commit()

    frappe.db.commit()


def _payment_reference_names(doctype):
    direct_names = frappe.db.sql(
        """
        select distinct reference_name
        from `tabPayment Intent`
        where reference_doctype=%s and coalesce(reference_name, '')!=''
        """,
        doctype,
        pluck=True,
    )
    names = set(direct_names)

    if doctype == 'Sales Invoice':
        names.update(
            frappe.db.sql(
                """
                select distinct sales_invoice
                from `tabPayment Intent`
                where coalesce(sales_invoice, '')!=''
                """,
                pluck=True,
            )
        )

    return sorted(names)


def _existing_reference_names(doctype, reference_names):
    if not reference_names:
        return []
    return frappe.get_all(
        doctype,
        filters={'name': ['in', reference_names]},
        pluck='name',
        limit_page_length=0,
    )


def _batches(values, batch_size):
    for start in range(0, len(values), batch_size):
        yield values[start : start + batch_size]
