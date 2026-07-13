import frappe
from frappe import _
from frappe.utils import cint, flt

from payment_orchestrator.logic import refresh_intent_and_reference
from payment_orchestrator.services import build_reference_context, update_reference_payment_summary


CORRECTION_TYPES = {
    "refresh_summary",
    "link_sales_invoice",
    "unlink_sales_invoice",
    "link_payment_entry",
    "unlink_payment_entry",
    "mark_expired",
    "mark_cancelled",
}

FINAL_PAID_STATUSES = {"Paid", "Partially Allocated", "Allocated", "Refunded"}
SNAPSHOT_FIELDS = [
    "name",
    "status",
    "reference_doctype",
    "reference_name",
    "sales_invoice",
    "payment_entry",
    "amount_requested",
    "amount_paid",
    "amount_refunded",
    "amount_allocated",
    "amount_unallocated",
    "allocation_status",
    "refund_status",
    "provider_payment_id",
    "payment_status",
    "qr_status",
    "modified",
    "modified_by",
]


@frappe.whitelist()
def apply_payment_intent_correction(
    payment_intent,
    correction_type,
    reason,
    sales_invoice=None,
    payment_entry=None,
    force=0,
):
    _require_correction_role()
    correction_type = _normalize_correction_type(correction_type)
    if correction_type not in CORRECTION_TYPES:
        frappe.throw(_("Unsupported correction type: {0}").format(correction_type))
    if not reason or not str(reason).strip():
        frappe.throw(_("Reason is required for Payment Intent corrections"))
    if not payment_intent or not frappe.db.exists("Payment Intent", payment_intent):
        frappe.throw(_("Payment Intent not found"))

    force = cint(force)
    intent = frappe.get_doc("Payment Intent", payment_intent)
    before = _snapshot_intent(intent)
    old_sales_invoice = intent.sales_invoice

    try:
        frappe.flags.payment_orchestrator_system_update = True
        result = _apply_correction(
            intent=intent,
            correction_type=correction_type,
            sales_invoice=sales_invoice,
            payment_entry=payment_entry,
            force=force,
        )
        intent.reload()
        _refresh_related_summaries(intent, old_sales_invoice=old_sales_invoice)
        after = _snapshot_intent(intent)
        log_name = _create_correction_log(
            intent=intent,
            correction_type=correction_type,
            reason=reason,
            sales_invoice=sales_invoice,
            payment_entry=payment_entry,
            force=force,
            before=before,
            after=after,
        )
        intent.add_comment(
            "Info",
            _("Payment Intent correction applied: {0}. Reason: {1}. Log: {2}").format(
                correction_type,
                reason,
                log_name,
            ),
        )
        return {
            "payment_intent": intent.name,
            "correction_type": correction_type,
            "correction_log": log_name,
            "result": result,
            "before": before,
            "after": after,
        }
    except Exception:
        _create_correction_log(
            intent=intent,
            correction_type=correction_type,
            reason=reason,
            sales_invoice=sales_invoice,
            payment_entry=payment_entry,
            force=force,
            before=before,
            after=_snapshot_intent(intent),
            status="Failed",
            error_message=frappe.get_traceback(),
        )
        raise
    finally:
        frappe.flags.payment_orchestrator_system_update = False


def _apply_correction(intent, correction_type, sales_invoice=None, payment_entry=None, force=0):
    if correction_type == "refresh_summary":
        return {"refreshed": True}
    if correction_type == "link_sales_invoice":
        _link_sales_invoice(intent, sales_invoice)
        return {"sales_invoice": sales_invoice}
    if correction_type == "unlink_sales_invoice":
        frappe.db.set_value("Payment Intent", intent.name, "sales_invoice", None, update_modified=False)
        return {"sales_invoice": None}
    if correction_type == "link_payment_entry":
        _link_payment_entry(intent, payment_entry, force=force)
        return {"payment_entry": payment_entry}
    if correction_type == "unlink_payment_entry":
        frappe.db.set_value("Payment Intent", intent.name, "payment_entry", None, update_modified=False)
        _rebuild_allocations_for_intent(intent.name, payment_entry=None)
        intent.reload()
        refresh_intent_and_reference(intent)
        return {"payment_entry": None}
    if correction_type == "mark_expired":
        _mark_unpaid_terminal(intent, "Expired")
        return {"status": "Expired"}
    if correction_type == "mark_cancelled":
        _mark_unpaid_terminal(intent, "Cancelled")
        return {"status": "Cancelled"}
    frappe.throw(_("Unsupported correction type: {0}").format(correction_type))


def _link_sales_invoice(intent, sales_invoice):
    if not sales_invoice:
        frappe.throw(_("Sales Invoice is required"))
    if not frappe.db.exists("Sales Invoice", sales_invoice):
        frappe.throw(_("Sales Invoice {0} not found").format(sales_invoice))
    invoice = frappe.get_doc("Sales Invoice", sales_invoice)
    if invoice.docstatus == 2:
        frappe.throw(_("Cannot link a cancelled Sales Invoice"))

    frappe.db.set_value("Payment Intent", intent.name, "sales_invoice", sales_invoice, update_modified=False)
    intent.reload()
    if intent.payment_entry and flt(intent.amount_paid or 0) > 0:
        _rebuild_allocations_for_intent(intent.name, payment_entry=intent.payment_entry)
        intent.reload()
        refresh_intent_and_reference(intent)


def _link_payment_entry(intent, payment_entry, force=0):
    if not payment_entry:
        frappe.throw(_("Payment Entry is required"))
    if not frappe.db.exists("Payment Entry", payment_entry):
        frappe.throw(_("Payment Entry {0} not found").format(payment_entry))
    pe = frappe.get_doc("Payment Entry", payment_entry)
    if pe.docstatus != 1:
        frappe.throw(_("Payment Entry must be submitted"))
    if pe.payment_type != "Receive":
        frappe.throw(_("Only Receive Payment Entries can be linked"))

    _validate_payment_entry_match(intent, pe, force=force)
    paid_amount = flt(intent.amount_paid or 0) or flt(pe.paid_amount or pe.received_amount or 0)
    updates = {
        "payment_entry": pe.name,
        "amount_paid": paid_amount,
        "amount_unallocated": paid_amount,
    }
    if not intent.provider_payment_id and pe.reference_no:
        updates["provider_payment_id"] = pe.reference_no
    frappe.db.set_value("Payment Intent", intent.name, updates, update_modified=False)

    intent.reload()
    _rebuild_allocations_for_intent(intent.name, payment_entry=pe.name)
    intent.reload()
    refresh_intent_and_reference(intent)


def _validate_payment_entry_match(intent, pe, force=0):
    reference_keys = {value for value in [intent.provider_payment_id, intent.name] if value}
    if pe.reference_no and pe.reference_no in reference_keys:
        return

    amount_matches = flt(pe.paid_amount or pe.received_amount or 0) == flt(intent.amount_paid or intent.amount_requested or 0)
    party_matches = _payment_entry_party_matches_intent(intent, pe)
    if force and amount_matches and party_matches:
        return

    frappe.throw(
        _(
            "Payment Entry does not safely match this Payment Intent. "
            "Reference No should match provider payment id / intent name, or use Force only when amount and party match."
        )
    )


def _payment_entry_party_matches_intent(intent, pe):
    try:
        context = build_reference_context(intent.reference_doctype, intent.reference_name)
    except Exception:
        return False
    expected_party = context.get("party")
    if expected_party and expected_party == pe.party:
        return True
    if intent.party and intent.party == pe.party:
        return True
    return bool(intent.party_name and intent.party_name == pe.party_name)


def _rebuild_allocations_for_intent(payment_intent, payment_entry=None):
    for allocation in frappe.get_all(
        "Payment Allocation",
        filters={"payment_intent": payment_intent, "status": ["!=", "Reversed"]},
        pluck="name",
    ):
        frappe.db.set_value("Payment Allocation", allocation, "status", "Reversed", update_modified=False)

    if not payment_entry:
        return

    intent = frappe.get_doc("Payment Intent", payment_intent)
    if not intent.sales_invoice:
        return

    pe = frappe.get_doc("Payment Entry", payment_entry)
    allocated = 0
    for ref in pe.references:
        if ref.reference_doctype == "Sales Invoice" and ref.reference_name == intent.sales_invoice:
            allocated += flt(ref.allocated_amount)

    if allocated <= 0:
        return

    allocation = frappe.get_doc({
        "doctype": "Payment Allocation",
        "status": "Allocated",
        "payment_intent": intent.name,
        "payment_entry": pe.name,
        "allocated_amount": allocated,
        "target_doctype": "Sales Invoice",
        "target_name": intent.sales_invoice,
        "allocation_date": frappe.utils.now_datetime(),
        "remarks": "Admin correction link from Payment Intent",
    })
    allocation.insert(ignore_permissions=True)


def _mark_unpaid_terminal(intent, status):
    if flt(intent.amount_paid or 0) > 0 or intent.status in FINAL_PAID_STATUSES:
        frappe.throw(_("Only unpaid non-final Payment Intents can be marked {0}").format(status))
    frappe.db.set_value(
        "Payment Intent",
        intent.name,
        {
            "status": status,
            "amount_paid": 0,
            "amount_allocated": 0,
            "amount_unallocated": 0,
            "allocation_status": "Unallocated",
            "last_synced_on": frappe.utils.now_datetime(),
        },
        update_modified=False,
    )


def _refresh_related_summaries(intent, old_sales_invoice=None):
    update_reference_payment_summary(intent.reference_doctype, intent.reference_name)
    if old_sales_invoice:
        update_reference_payment_summary("Sales Invoice", old_sales_invoice)
    if intent.sales_invoice:
        update_reference_payment_summary("Sales Invoice", intent.sales_invoice)


def _snapshot_intent(intent):
    intent.reload()
    return {field: intent.get(field) for field in SNAPSHOT_FIELDS if hasattr(intent, field)}


def _create_correction_log(
    intent,
    correction_type,
    reason,
    sales_invoice=None,
    payment_entry=None,
    force=0,
    before=None,
    after=None,
    status="Applied",
    error_message=None,
):
    log = frappe.get_doc({
        "doctype": "Payment Intent Correction Log",
        "payment_intent": intent.name,
        "correction_type": correction_type,
        "status": status,
        "reason": reason,
        "sales_invoice": sales_invoice,
        "payment_entry": payment_entry,
        "force": cint(force),
        "before_json": frappe.as_json(before or {}, indent=2),
        "after_json": frappe.as_json(after or {}, indent=2),
        "error_message": error_message,
    })
    log.insert(ignore_permissions=True)
    return log.name


def _normalize_correction_type(correction_type):
    return str(correction_type or "").strip().lower().replace(" ", "_")


def _require_correction_role():
    roles = set(frappe.get_roles(frappe.session.user))
    if not roles.intersection({"System Manager", "Payment Orchestrator Manager"}):
        frappe.throw(_("Not permitted to apply Payment Intent corrections"), frappe.PermissionError)
