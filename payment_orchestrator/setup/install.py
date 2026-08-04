import json

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.utils import cint

from payment_orchestrator.utils import ensure_required_modes_of_payment


LINKED_REFERENCE_DOCTYPE = "Payment Intent"
SALES_INVOICE_PAYMENT_SUMMARY_ANCHOR = "si_support_actions_html"
PATIENT_ENCOUNTER_PAYMENT_SUMMARY_ANCHOR = "enc_multi_payments"
PAYMENT_SUMMARY_DEPENDS_ON = (
    "eval:doc.po_last_payment_intent"
    " || (doc.po_total_requested || 0) > 0"
    " || (doc.po_total_paid || 0) > 0"
    " || (doc.po_total_allocated || 0) > 0"
    " || (doc.po_total_unallocated || 0) > 0"
)
PAYMENT_STATUS_OPTIONS = "\n".join([
    "Not Requested",
    "Awaiting Payment",
    "Partially Received",
    "Payment Received",
    "Partially Allocated",
    "Allocated",
    "Partially Refunded",
    "Refunded",
    "Payment Failed",
    "Expired",
    "Cancelled",
])


def _payment_status_field():
    return {
        'fieldname': 'po_payment_status',
        'label': 'Payment Status',
        'fieldtype': 'Select',
        'options': PAYMENT_STATUS_OPTIONS,
        'insert_after': 'po_total_unallocated',
        'default': None,
        'read_only': 1,
        'allow_on_submit': 1,
        'in_list_view': 1,
        'in_standard_filter': 0,
        'search_index': 0,
    }


def _summary_currency_field(fieldname, label, insert_after):
    return {
        'fieldname': fieldname,
        'label': label,
        'fieldtype': 'Currency',
        'insert_after': insert_after,
        'read_only': 1,
        'allow_on_submit': 1,
    }


def _latest_payment_intent_field():
    return {
        'fieldname': 'po_last_payment_intent',
        'label': 'Latest Payment Intent',
        'fieldtype': 'Link',
        'options': 'Payment Intent',
        'insert_after': 'po_payment_status',
        'read_only': 1,
        'allow_on_submit': 1,
    }


REFERENCE_SUMMARY_FIELDS = {
    'CRM Lead': [
        {'fieldname': 'po_payment_tab', 'label': 'Payment Summary', 'fieldtype': 'Tab Break', 'insert_after': 'lead_name', 'depends_on': PAYMENT_SUMMARY_DEPENDS_ON},
        _summary_currency_field('po_total_requested', 'Total Requested', 'po_payment_tab'),
        _summary_currency_field('po_total_paid', 'Total Paid', 'po_total_requested'),
        _summary_currency_field('po_total_allocated', 'Total Allocated', 'po_total_paid'),
        _summary_currency_field('po_total_unallocated', 'Total Unallocated', 'po_total_allocated'),
        _payment_status_field(),
        _latest_payment_intent_field(),
        {'fieldname': 'po_payment_dashboard_html', 'label': 'Payment Dashboard', 'fieldtype': 'HTML', 'insert_after': 'po_last_payment_intent'},
    ],
    'Patient Encounter': [
        {'fieldname': 'po_payment_tab', 'label': 'Payment Summary', 'fieldtype': 'Tab Break', 'insert_after': PATIENT_ENCOUNTER_PAYMENT_SUMMARY_ANCHOR, 'depends_on': PAYMENT_SUMMARY_DEPENDS_ON},
        _summary_currency_field('po_total_requested', 'Total Requested', 'po_payment_tab'),
        _summary_currency_field('po_total_paid', 'Total Paid', 'po_total_requested'),
        _summary_currency_field('po_total_allocated', 'Total Allocated', 'po_total_paid'),
        _summary_currency_field('po_total_unallocated', 'Total Unallocated', 'po_total_allocated'),
        _payment_status_field(),
        _latest_payment_intent_field(),
        {'fieldname': 'po_payment_dashboard_html', 'label': 'Payment Dashboard', 'fieldtype': 'HTML', 'insert_after': 'po_last_payment_intent'},
    ],
    'Sales Order': [
        {'fieldname': 'po_payment_tab', 'label': 'Payment Summary', 'fieldtype': 'Tab Break', 'insert_after': 'payment_schedule', 'depends_on': PAYMENT_SUMMARY_DEPENDS_ON},
        _summary_currency_field('po_total_requested', 'Total Requested', 'po_payment_tab'),
        _summary_currency_field('po_total_paid', 'Total Paid', 'po_total_requested'),
        _summary_currency_field('po_total_allocated', 'Total Allocated', 'po_total_paid'),
        _summary_currency_field('po_total_unallocated', 'Total Unallocated', 'po_total_allocated'),
        _payment_status_field(),
        _latest_payment_intent_field(),
        {'fieldname': 'po_payment_dashboard_html', 'label': 'Payment Dashboard', 'fieldtype': 'HTML', 'insert_after': 'po_last_payment_intent'},
    ],
    'Sales Invoice': [
        {'fieldname': 'po_payment_tab', 'label': 'Payment Summary', 'fieldtype': 'Tab Break', 'insert_after': SALES_INVOICE_PAYMENT_SUMMARY_ANCHOR, 'depends_on': PAYMENT_SUMMARY_DEPENDS_ON},
        _summary_currency_field('po_total_requested', 'Total Requested', 'po_payment_tab'),
        _summary_currency_field('po_total_paid', 'Total Paid', 'po_total_requested'),
        _summary_currency_field('po_total_allocated', 'Total Allocated', 'po_total_paid'),
        _summary_currency_field('po_total_unallocated', 'Total Unallocated', 'po_total_allocated'),
        _payment_status_field(),
        _latest_payment_intent_field(),
        {'fieldname': 'po_payment_dashboard_html', 'label': 'Payment Dashboard', 'fieldtype': 'HTML', 'insert_after': 'po_last_payment_intent'},
    ],
}


def _reference_summary_fields_for_install():
    """Avoid install-time failures if linked doctypes are not yet resolvable during validation."""
    can_link_payment_intent = bool(frappe.db.exists("DocType", LINKED_REFERENCE_DOCTYPE))
    filtered = {}

    for dt, fields in REFERENCE_SUMMARY_FIELDS.items():
        if not frappe.db.exists("DocType", dt):
            continue
        filtered[dt] = []
        for df in fields:
            if (
                df.get("fieldtype") == "Link"
                and df.get("options") == LINKED_REFERENCE_DOCTYPE
                and not can_link_payment_intent
            ):
                # Skip for now; app install should not fail because a summary backlink field
                # validates before the linked DocType is fully available.
                continue
            filtered[dt].append(df)

    return filtered


def after_install():
    create_custom_fields(_reference_summary_fields_for_install(), update=True)
    sync_reference_field_placement()
    sync_reference_field_visibility()
    ensure_default_modes_of_payment()
    frappe.db.commit()


def sync_reference_field_placement():
    sync_reference_field_labels()

    sync_patient_encounter_field_placement()
    sync_sales_invoice_field_placement()


def sync_patient_encounter_field_placement():
    if not frappe.db.exists("DocType", "Patient Encounter"):
        return

    anchor = _patient_encounter_payment_summary_anchor()
    _sync_reference_fields_for_doctype("Patient Encounter", anchor)
    frappe.clear_cache(doctype="Patient Encounter")


def sync_sales_invoice_field_placement():
    if not frappe.db.exists("DocType", "Sales Invoice"):
        return

    anchor = _sales_invoice_payment_summary_anchor()
    _sync_reference_fields_for_doctype("Sales Invoice", anchor)
    frappe.clear_cache(doctype="Sales Invoice")


def _sync_reference_fields_for_doctype(dt: str, anchor: str):
    payment_fields = REFERENCE_SUMMARY_FIELDS.get(dt, [])
    anchor_idx = _field_idx(dt, anchor) or 0

    for offset, field in enumerate(payment_fields, 1):
        custom_field = f"{dt}-{field['fieldname']}"
        if not frappe.db.exists("Custom Field", custom_field):
            continue

        updates = {"idx": anchor_idx + offset}
        if field["fieldname"] == "po_payment_tab":
            updates.update({
                "label": field["label"],
                "insert_after": anchor,
            })
        else:
            updates["insert_after"] = field["insert_after"]
        frappe.db.set_value("Custom Field", custom_field, updates, update_modified=False)

    _sync_field_order(dt, anchor, [field["fieldname"] for field in payment_fields])


def sync_reference_field_labels():
    for dt, fields in REFERENCE_SUMMARY_FIELDS.items():
        if not frappe.db.exists("DocType", dt):
            continue
        for field in fields:
            custom_field = f"{dt}-{field['fieldname']}"
            if frappe.db.exists("Custom Field", custom_field):
                frappe.db.set_value(
                    "Custom Field",
                    custom_field,
                    "label",
                    field["label"],
                    update_modified=False,
                )
        frappe.clear_cache(doctype=dt)


def _sales_invoice_payment_summary_anchor() -> str:
    if frappe.db.exists("Custom Field", f"Sales Invoice-{SALES_INVOICE_PAYMENT_SUMMARY_ANCHOR}"):
        return SALES_INVOICE_PAYMENT_SUMMARY_ANCHOR
    if frappe.db.exists("Custom Field", "Sales Invoice-si_shipkia_shipment"):
        return "si_shipkia_shipment"
    return "payments_tab"


def _patient_encounter_payment_summary_anchor() -> str:
    if frappe.db.exists("Custom Field", f"Patient Encounter-{PATIENT_ENCOUNTER_PAYMENT_SUMMARY_ANCHOR}"):
        return PATIENT_ENCOUNTER_PAYMENT_SUMMARY_ANCHOR
    if frappe.db.exists("DocField", {"parent": "Patient Encounter", "fieldname": "clinical_notes"}):
        return "clinical_notes"
    return "encounter_details"


def _field_idx(dt: str, fieldname: str) -> int:
    custom_idx = frappe.db.get_value("Custom Field", {"dt": dt, "fieldname": fieldname}, "idx")
    if custom_idx is not None:
        return cint(custom_idx)

    standard_idx = frappe.db.get_value("DocField", {"parent": dt, "fieldname": fieldname}, "idx")
    return cint(standard_idx)


def _sync_field_order(dt: str, anchor: str, payment_fieldnames: list[str]):
    property_setters = frappe.get_all(
        "Property Setter",
        filters={
            "doc_type": dt,
            "property": "field_order",
        },
        pluck="name",
    )
    if not property_setters:
        return

    for property_setter in property_setters:
        value = frappe.db.get_value("Property Setter", property_setter, "value")
        if not value:
            continue
        try:
            field_order = json.loads(value)
        except ValueError:
            continue

        field_order = [fieldname for fieldname in field_order if fieldname not in payment_fieldnames]
        insert_at = field_order.index(anchor) + 1 if anchor in field_order else len(field_order)
        field_order[insert_at:insert_at] = payment_fieldnames
        frappe.db.set_value(
            "Property Setter",
            property_setter,
            "value",
            json.dumps(field_order),
            update_modified=False,
        )


def sync_reference_field_visibility():
    settings = frappe.get_single("Payment Orchestrator Settings")
    enabled_by_doctype = {
        "CRM Lead": _enabled_setting(settings, "enable_on_crm_lead"),
        "Patient Encounter": _enabled_setting(settings, "enable_on_patient_encounter"),
        "Sales Order": _enabled_setting(settings, "enable_on_sales_order"),
        "Sales Invoice": _enabled_setting(settings, "enable_on_sales_invoice"),
    }

    for dt, enabled in enabled_by_doctype.items():
        if not frappe.db.exists("DocType", dt):
            continue
        hidden = 0 if enabled else 1
        for field in REFERENCE_SUMMARY_FIELDS.get(dt, []):
            custom_field = f"{dt}-{field['fieldname']}"
            if frappe.db.exists("Custom Field", custom_field):
                updates = {"hidden": hidden}
                if field["fieldname"] == "po_payment_status":
                    updates.update({
                        "in_list_view": enabled,
                        "in_standard_filter": 0,
                        "search_index": 0,
                    })
                frappe.db.set_value("Custom Field", custom_field, updates, update_modified=False)
        frappe.clear_cache(doctype=dt)


def _enabled_setting(settings, fieldname: str) -> int:
    value = getattr(settings, fieldname, None)
    return 1 if value is None else cint(value)


def ensure_default_modes_of_payment():
    ensure_required_modes_of_payment()
