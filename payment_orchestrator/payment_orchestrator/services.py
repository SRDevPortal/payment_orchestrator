import frappe
from frappe.utils import add_to_date, cint

from payment_orchestrator.utils import (
    get_settings,
    is_doctype_enabled,
    is_gateway_mode_enabled,
    get_provider_mode_for_gateway_mode,
    get_default_request_type,
    now_ts,
)


DOCTYPE_FIELD_MAP = {
    'CRM Lead': {
        'party_type': 'Lead',
        'name_field': 'lead_name',
        'email_fields': ['email', 'email_id'],
        'mobile_fields': ['mobile_no', 'phone', 'phone_no'],
    },
    'Patient Encounter': {
        'party_type': 'Patient',
        'name_field': 'patient_name',
        'email_fields': [],
        'mobile_fields': ['sr_pe_mobile'],
    },
    'Sales Order': {
        'party_type': 'Customer',
        'name_field': 'customer_name',
        'email_fields': ['contact_email'],
        'mobile_fields': ['contact_mobile', 'mobile_no'],
    },
    'Sales Invoice': {
        'party_type': 'Customer',
        'name_field': 'customer_name',
        'email_fields': ['contact_email'],
        'mobile_fields': ['contact_mobile'],
    },
}


def build_reference_context(reference_doctype: str, reference_name: str) -> dict:
    if not frappe.db.exists(reference_doctype, reference_name):
        frappe.throw(f'{reference_doctype} {reference_name} not found')

    doc = frappe.get_doc(reference_doctype, reference_name)
    meta = DOCTYPE_FIELD_MAP.get(reference_doctype, {})

    data = {
        'reference_doctype': reference_doctype,
        'reference_name': reference_name,
        'company': getattr(doc, 'company', None) or getattr(get_settings(), 'company', None),
        'party_type': meta.get('party_type'),
        'party': None,
        'party_name': getattr(doc, meta.get('name_field', 'name'), None) or getattr(doc, 'name', None),
        'email': _first_value(doc, meta.get('email_fields', [])),
        'mobile': _first_value(doc, meta.get('mobile_fields', [])),
        'outstanding_amount': getattr(doc, 'outstanding_amount', None),
        'grand_total': getattr(doc, 'grand_total', None),
        'lead': None,
        'patient': getattr(doc, 'patient', None) if reference_doctype == 'Patient Encounter' else None,
        'encounter': reference_name if reference_doctype == 'Patient Encounter' else getattr(doc, 'patient_encounter', None),
        'sales_order': reference_name if reference_doctype == 'Sales Order' else getattr(doc, 'sales_order', None),
        'sales_invoice': reference_name if reference_doctype == 'Sales Invoice' else None,
    }

    if reference_doctype in ('Sales Order', 'Sales Invoice'):
        data['party'] = getattr(doc, 'customer', None)
    elif reference_doctype == 'Patient Encounter':
        data['party'] = getattr(doc, 'patient', None)
    elif reference_doctype == 'CRM Lead':
        data['party'] = reference_name
    else:
        data['party'] = reference_name

    return data


def create_payment_intent_doc(
    reference_doctype: str,
    reference_name: str,
    amount,
    request_type=None,
    request_channel=None,
    notes=None,
    gateway=None,
    payment_mode=None,
):
    settings = get_settings()
    if not settings.provider_enabled:
        frappe.throw('Payment provider is disabled in Payment Orchestrator Settings')
    if not is_doctype_enabled(reference_doctype):
        frappe.throw(f'Payment requests are disabled for {reference_doctype}')
    request_channel = request_channel or settings.default_request_channel
    payment_mode = payment_mode or request_channel or 'Payment Link'
    gateway = gateway or _default_gateway_for_mode(payment_mode)

    if payment_mode == 'QR Code':
        if not is_gateway_mode_enabled(gateway, 'QR Code', settings=settings):
            frappe.throw(f'{gateway} QR Code generation is disabled in Payment Orchestrator Settings')
    elif request_channel != 'POS' and not (
        is_gateway_mode_enabled('Razorpay', 'Payment Link', settings=settings)
        or is_gateway_mode_enabled('Pine Labs', 'Payment Link', settings=settings)
    ):
        frappe.throw('Payment link generation is disabled in Payment Orchestrator Settings')
    if request_channel == 'POS' and not (
        is_gateway_mode_enabled('Razorpay', 'POS', settings=settings)
        or is_gateway_mode_enabled('Pine Labs', 'POS', settings=settings)
    ):
        frappe.throw('POS payments are disabled in Payment Orchestrator Settings')

    context = build_reference_context(reference_doctype, reference_name)

    intent = frappe.get_doc({
        'doctype': 'Payment Intent',
        'status': 'Requested',
        'allocation_status': 'Unallocated',
        'gateway': gateway,
        'payment_mode': payment_mode,
        'provider': gateway or 'Payment Orchestrator',
        'provider_mode': get_provider_mode_for_gateway_mode(gateway, payment_mode, settings=settings),
        'company': context.get('company'),
        'request_type': request_type or get_default_request_type(reference_doctype),
        'request_channel': request_channel,
        'amount_requested': amount,
        'amount_paid': 0,
        'amount_allocated': 0,
        'amount_unallocated': 0,
        'currency': settings.default_currency,
        'reference_doctype': reference_doctype,
        'reference_name': reference_name,
        'party_type': context.get('party_type'),
        'party': context.get('party'),
        'party_name': context.get('party_name'),
        'party_email': context.get('email'),
        'party_mobile': context.get('mobile'),
        'lead': context.get('lead'),
        'patient': context.get('patient'),
        'encounter': context.get('encounter'),
        'sales_order': context.get('sales_order'),
        'sales_invoice': context.get('sales_invoice'),
        'requested_on': now_ts(),
        'expires_on': add_to_date(now_ts(), hours=settings.payment_link_expiry_hours),
        'requested_by': frappe.session.user,
        'request_source': 'Manual ERP Action',
        'notes': notes,
    })
    intent.insert(ignore_permissions=True)
    _update_reference_summary(reference_doctype, reference_name)
    return intent, context


def _default_gateway_for_mode(payment_mode):
    if payment_mode == 'POS':
        return 'Pine Labs'
    return 'Razorpay'


def get_allocation_targets(intent) -> list[dict]:
    settings = get_settings()
    targets = []
    if intent.reference_doctype == 'Sales Invoice' and intent.sales_invoice:
        targets.append({'doctype': 'Sales Invoice', 'name': intent.sales_invoice, 'priority': 1})
    if intent.reference_doctype == 'Patient Encounter' and cint(settings.auto_allocate_encounter_advances):
        for row in _get_linked_invoices_for_encounter(intent.encounter or intent.reference_name):
            targets.append({'doctype': 'Sales Invoice', 'name': row, 'priority': 2})
    if intent.reference_doctype == 'Sales Order' and cint(settings.auto_allocate_sales_order_advances):
        for row in _get_linked_invoices_for_sales_order(intent.sales_order or intent.reference_name):
            targets.append({'doctype': 'Sales Invoice', 'name': row, 'priority': 3})
    return targets


def update_reference_payment_summary(reference_doctype: str, reference_name: str) -> dict:
    total_requested = frappe.db.sql(
        """
        select coalesce(sum(amount_requested), 0) as total_requested,
               coalesce(sum(amount_paid), 0) as total_paid,
               coalesce(sum(amount_allocated), 0) as total_allocated,
               coalesce(sum(amount_unallocated), 0) as total_unallocated
        from `tabPayment Intent`
        where reference_doctype=%s and reference_name=%s
        """,
        (reference_doctype, reference_name),
        as_dict=True,
    )[0]

    meta = frappe.get_meta(reference_doctype)
    updates = {}
    if meta.get_field('po_total_requested'):
        updates['po_total_requested'] = total_requested.total_requested
    if meta.get_field('po_total_paid'):
        updates['po_total_paid'] = total_requested.total_paid
    if meta.get_field('po_total_allocated'):
        updates['po_total_allocated'] = total_requested.total_allocated
    if meta.get_field('po_total_unallocated'):
        updates['po_total_unallocated'] = total_requested.total_unallocated
    if meta.get_field('po_last_payment_intent'):
        latest = frappe.db.get_value('Payment Intent', {'reference_doctype': reference_doctype, 'reference_name': reference_name}, 'name', order_by='modified desc')
        updates['po_last_payment_intent'] = latest

    if updates:
        frappe.db.set_value(reference_doctype, reference_name, updates, update_modified=False)

    return {
        'reference_doctype': reference_doctype,
        'reference_name': reference_name,
        **updates,
        'total_requested': total_requested.total_requested,
        'total_paid': total_requested.total_paid,
        'total_allocated': total_requested.total_allocated,
        'total_unallocated': total_requested.total_unallocated,
    }


def _update_reference_summary(reference_doctype: str, reference_name: str):
    settings = get_settings()
    if cint(settings.enable_payment_summary_sync):
        update_reference_payment_summary(reference_doctype, reference_name)


def _first_value(doc, fieldnames):
    for fieldname in fieldnames or []:
        value = getattr(doc, fieldname, None)
        if value:
            return value
    return None


def _get_linked_invoices_for_encounter(encounter_name):
    if not encounter_name:
        return []
    possible_fields = ['patient_encounter', 'custom_patient_encounter', 'encounter']
    found = []
    meta = frappe.get_meta('Sales Invoice')
    for fieldname in possible_fields:
        if meta.get_field(fieldname):
            names = frappe.get_all('Sales Invoice', filters={fieldname: encounter_name, 'docstatus': ['<', 2]}, pluck='name')
            found.extend(names)
    return list(dict.fromkeys(found))


def _get_linked_invoices_for_sales_order(sales_order_name):
    if not sales_order_name:
        return []
    return frappe.get_all('Sales Invoice', filters={'sales_order': sales_order_name, 'docstatus': ['<', 2]}, pluck='name')
