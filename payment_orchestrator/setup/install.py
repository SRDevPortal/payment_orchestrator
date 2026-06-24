import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


LINKED_REFERENCE_DOCTYPE = "Payment Intent"


REFERENCE_SUMMARY_FIELDS = {
    'CRM Lead': [
        {'fieldname': 'po_payment_tab', 'label': 'Payments', 'fieldtype': 'Tab Break', 'insert_after': 'lead_name'},
        {'fieldname': 'po_total_requested', 'label': 'Total Requested', 'fieldtype': 'Currency', 'insert_after': 'po_payment_tab', 'read_only': 1},
        {'fieldname': 'po_total_paid', 'label': 'Total Paid', 'fieldtype': 'Currency', 'insert_after': 'po_total_requested', 'read_only': 1},
        {'fieldname': 'po_total_allocated', 'label': 'Total Allocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_paid', 'read_only': 1},
        {'fieldname': 'po_total_unallocated', 'label': 'Total Unallocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_allocated', 'read_only': 1},
        {'fieldname': 'po_last_payment_intent', 'label': 'Last Payment Intent', 'fieldtype': 'Link', 'options': 'Payment Intent', 'insert_after': 'po_total_unallocated', 'read_only': 1},
    ],
    'Patient Encounter': [
        {'fieldname': 'po_payment_tab', 'label': 'Payments', 'fieldtype': 'Tab Break', 'insert_after': 'enc_multi_payments'},
        {'fieldname': 'po_total_requested', 'label': 'Total Requested', 'fieldtype': 'Currency', 'insert_after': 'po_payment_tab', 'read_only': 1},
        {'fieldname': 'po_total_paid', 'label': 'Total Paid', 'fieldtype': 'Currency', 'insert_after': 'po_total_requested', 'read_only': 1},
        {'fieldname': 'po_total_allocated', 'label': 'Total Allocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_paid', 'read_only': 1},
        {'fieldname': 'po_total_unallocated', 'label': 'Total Unallocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_allocated', 'read_only': 1},
        {'fieldname': 'po_last_payment_intent', 'label': 'Last Payment Intent', 'fieldtype': 'Link', 'options': 'Payment Intent', 'insert_after': 'po_total_unallocated', 'read_only': 1},
    ],
    'Sales Order': [
        {'fieldname': 'po_payment_tab', 'label': 'Payments', 'fieldtype': 'Tab Break', 'insert_after': 'payment_schedule'},
        {'fieldname': 'po_total_requested', 'label': 'Total Requested', 'fieldtype': 'Currency', 'insert_after': 'po_payment_tab', 'read_only': 1},
        {'fieldname': 'po_total_paid', 'label': 'Total Paid', 'fieldtype': 'Currency', 'insert_after': 'po_total_requested', 'read_only': 1},
        {'fieldname': 'po_total_allocated', 'label': 'Total Allocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_paid', 'read_only': 1},
        {'fieldname': 'po_total_unallocated', 'label': 'Total Unallocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_allocated', 'read_only': 1},
        {'fieldname': 'po_last_payment_intent', 'label': 'Last Payment Intent', 'fieldtype': 'Link', 'options': 'Payment Intent', 'insert_after': 'po_total_unallocated', 'read_only': 1},
    ],
    'Sales Invoice': [
        {'fieldname': 'po_payment_tab', 'label': 'Payments', 'fieldtype': 'Tab Break', 'insert_after': 'payments_tab'},
        {'fieldname': 'po_total_requested', 'label': 'Total Requested', 'fieldtype': 'Currency', 'insert_after': 'po_payment_tab', 'read_only': 1},
        {'fieldname': 'po_total_paid', 'label': 'Total Paid', 'fieldtype': 'Currency', 'insert_after': 'po_total_requested', 'read_only': 1},
        {'fieldname': 'po_total_allocated', 'label': 'Total Allocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_paid', 'read_only': 1},
        {'fieldname': 'po_total_unallocated', 'label': 'Total Unallocated', 'fieldtype': 'Currency', 'insert_after': 'po_total_allocated', 'read_only': 1},
        {'fieldname': 'po_last_payment_intent', 'label': 'Last Payment Intent', 'fieldtype': 'Link', 'options': 'Payment Intent', 'insert_after': 'po_total_unallocated', 'read_only': 1},
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
    ensure_default_modes_of_payment()
    frappe.db.commit()


def ensure_default_modes_of_payment():
    for mode in ("Razorpay", "Pine Labs", "Pine Labs POS"):
        if not frappe.db.exists("Mode of Payment", mode):
            frappe.get_doc({
                "doctype": "Mode of Payment",
                "mode_of_payment": mode,
                "enabled": 1,
            }).insert(ignore_permissions=True)
