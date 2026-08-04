import frappe
from frappe.utils import flt

from payment_orchestrator.api.common.validation import ensure_payment_intent_action_permission
from payment_orchestrator.logic import allocate_available_amount, refresh_intent_and_reference
from payment_orchestrator.utils import is_doctype_enabled


REFERENCE_SUMMARY_VALUE_FIELDS = (
    'po_total_requested',
    'po_total_paid',
    'po_total_allocated',
    'po_total_unallocated',
    'po_payment_status',
    'po_last_payment_intent',
)


@frappe.whitelist()
def auto_allocate(payment_intent):
    intent = frappe.get_doc('Payment Intent', payment_intent)
    ensure_payment_intent_action_permission(intent)
    payment_entry = _resolve_payment_entry(intent)
    if not payment_entry:
        frappe.throw('No Payment Entry linked to this payment intent yet')
    allocated = allocate_available_amount(intent, payment_entry)
    refresh_intent_and_reference(intent)
    return {
        'payment_intent': intent.name,
        'allocated_amount': allocated,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


@frappe.whitelist()
def sync_reference_summary(reference_doctype=None, reference_name=None, doc=None, method=None):
    from payment_orchestrator.services import (
        reference_has_payment_intents,
        update_reference_payment_summary,
    )

    if getattr(reference_doctype, "doctype", None) and not isinstance(reference_doctype, str):
        doc = reference_doctype
        reference_doctype = None
        reference_name = None

    if doc is not None:
        reference_doctype = doc.doctype
        reference_name = doc.name
    if not reference_doctype or not reference_name:
        return None
    if not is_doctype_enabled(reference_doctype):
        return None

    if doc is None or not _has_payment_summary_state(doc):
        if not reference_has_payment_intents(reference_doctype, reference_name):
            return None

    summary = update_reference_payment_summary(reference_doctype, reference_name)
    if doc is not None:
        _apply_payment_summary_to_doc(doc, summary)
    return summary


def _has_payment_summary_state(doc):
    if doc.get('po_last_payment_intent'):
        return True
    if any(flt(doc.get(fieldname)) > 0 for fieldname in REFERENCE_SUMMARY_VALUE_FIELDS[:4]):
        return True
    return str(doc.get('po_payment_status') or '').strip() not in ('', 'Not Requested')


def _apply_payment_summary_to_doc(doc, summary):
    for fieldname in REFERENCE_SUMMARY_VALUE_FIELDS:
        if fieldname in summary:
            doc.set(fieldname, summary[fieldname])


def _resolve_payment_entry(intent):
    return frappe.db.get_value('Payment Entry', {'reference_no': ['in', [intent.provider_payment_id, intent.name]]}, 'name')
