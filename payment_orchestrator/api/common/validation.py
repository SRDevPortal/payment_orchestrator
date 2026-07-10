import frappe
from frappe.utils import flt

from payment_orchestrator.utils import get_settings

DEFAULT_PAYMENT_ACTION_ROLES = {"Accounts Manager", "Accounts User", "System Manager"}


def allow_partial(settings, reference_doctype):
    mapping = {
        "CRM Lead": getattr(settings, "crm_lead_allow_partial_payment", 1),
        "Patient Encounter": settings.encounter_allow_partial_payment,
        "Sales Order": settings.sales_order_allow_partial_payment,
        "Sales Invoice": settings.sales_invoice_allow_partial_payment,
    }
    return bool(mapping.get(reference_doctype))


def validate_reference_payment_request(reference_doctype, reference_name, amount, settings=None):
    settings = settings or get_settings()
    if not reference_doctype or not reference_name:
        frappe.throw("Reference Doctype and Reference Name are required")

    if not frappe.db.exists(reference_doctype, reference_name):
        frappe.throw(f"{reference_doctype} {reference_name} not found")

    ensure_reference_read_permission(reference_doctype, reference_name)

    doc = frappe.get_doc(reference_doctype, reference_name)
    if reference_doctype == "Patient Encounter":
        validate_patient_encounter_request(doc)
    elif reference_doctype == "Sales Invoice":
        validate_sales_invoice_request(doc, amount, settings=settings)


def ensure_reference_read_permission(reference_doctype, reference_name):
    doc = frappe.get_doc(reference_doctype, reference_name)
    if not doc.has_permission("read"):
        frappe.throw(f"Not permitted to access {reference_doctype} {reference_name}", frappe.PermissionError)


def ensure_payment_action_permission():
    if not has_payment_action_permission():
        frappe.throw("Not permitted to perform payment actions", frappe.PermissionError)


def has_payment_action_permission(user=None, settings=None):
    user = user or frappe.session.user
    roles = set(frappe.get_roles(user))
    if "System Manager" in roles:
        return True

    settings = settings or get_settings()
    allowed_roles = payment_action_roles(settings)
    allowed_role_profiles = payment_action_role_profiles(settings)

    if roles.intersection(allowed_roles):
        return True

    role_profile = frappe.db.get_value("User", user, "role_profile_name")
    return bool(role_profile and role_profile in allowed_role_profiles)


def payment_action_roles(settings=None):
    settings = settings or get_settings()
    roles = _child_values(settings, "allowed_payment_action_roles", "role")
    return roles or set(DEFAULT_PAYMENT_ACTION_ROLES)


def payment_action_role_profiles(settings=None):
    settings = settings or get_settings()
    return _child_values(settings, "allowed_payment_action_role_profiles", "role_profile")


def _child_values(doc, table_fieldname, value_fieldname):
    rows = getattr(doc, table_fieldname, None) or []
    return {
        str(getattr(row, value_fieldname, "") or "").strip()
        for row in rows
        if str(getattr(row, value_fieldname, "") or "").strip()
    }


def ensure_payment_intent_read_permission(intent):
    ensure_reference_read_permission(intent.reference_doctype, intent.reference_name)


def ensure_payment_intent_action_permission(intent):
    ensure_payment_action_permission()
    ensure_payment_intent_read_permission(intent)


def validate_patient_encounter_request(doc):
    if int(getattr(doc, "docstatus", 0) or 0) != 0:
        frappe.throw("Payment request can be generated only for a draft Patient Encounter")

    encounter_type = getattr(doc, "sr_encounter_type", None)
    if encounter_type and encounter_type != "Order":
        frappe.throw("Payment request can be generated only for Order Patient Encounters")


def validate_sales_invoice_request(doc, amount, settings=None):
    if int(getattr(doc, "docstatus", 0) or 0) != 1:
        frappe.throw("Payment request can be generated only for a submitted Sales Invoice")

    outstanding = flt(getattr(doc, "outstanding_amount", 0))
    if outstanding <= 0:
        frappe.throw("Sales Invoice has no outstanding amount to collect")

    if flt(amount) > outstanding and not getattr(settings, "allow_overpayment", 0):
        frappe.throw("Amount cannot be greater than invoice outstanding amount")
