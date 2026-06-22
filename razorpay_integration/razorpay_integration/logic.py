import frappe
from frappe.utils import flt, nowdate

from razorpay_integration.services import (
    build_reference_context,
    get_allocation_targets,
    update_reference_payment_summary,
)
from razorpay_integration.utils import as_json, get_settings


def process_provider_payment_success(payload, event_doc=None):
    payment_entity = _extract_payment_entity(payload)
    notes = payment_entity.get('notes', {}) or {}
    payment_intent_name = notes.get('payment_intent') or _find_intent_by_provider_ids(payment_entity)
    if not payment_intent_name:
        frappe.throw('Unable to resolve Payment Intent from webhook payload')

    intent = frappe.get_doc('Payment Intent', payment_intent_name)
    if intent.provider_payment_id and intent.provider_payment_id == payment_entity.get('id'):
        existing_pe = _existing_payment_entry(intent)
        return {'payment_intent': intent.name, 'payment_entry': existing_pe, 'duplicate': True}

    amount_paid = flt(payment_entity.get('amount', 0)) / 100
    settings = get_settings()
    if amount_paid > flt(intent.amount_requested or 0) and not getattr(settings, 'allow_overpayment', 0):
        frappe.throw('Provider payment amount is greater than requested amount')

    intent.db_set('provider_payment_id', payment_entity.get('id'))
    intent.db_set('provider_event_id', payment_entity.get('id'))
    intent.db_set('provider_pos_request_id', payment_entity.get('pos_request_id') or payment_entity.get('payment_request_id') or intent.provider_pos_request_id)
    intent.db_set('provider_order_id', payment_entity.get('order_id') or intent.provider_order_id)
    intent.db_set('provider_terminal_id', payment_entity.get('terminal_id') or payment_entity.get('device_id') or intent.provider_terminal_id)
    intent.db_set('payment_status', payment_entity.get('status'))
    if intent.request_channel == 'POS':
        intent.db_set('pos_request_status', payment_entity.get('status') or 'paid')
    intent.db_set('amount_paid', amount_paid)
    intent.db_set('amount_unallocated', amount_paid)
    intent.db_set('paid_on', frappe.utils.now_datetime())
    intent.db_set('provider_payload_snapshot', as_json(payload))

    payment_entry_name = create_payment_entry_for_intent(intent)
    allocated_amount = 0
    if settings.enable_auto_allocation:
        allocated_amount = allocate_available_amount(intent, payment_entry_name)

    refresh_intent_and_reference(intent)

    return {
        'payment_intent': intent.name,
        'payment_entry': payment_entry_name,
        'allocated_amount': allocated_amount,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


def create_payment_entry_for_intent(intent):
    existing = _existing_payment_entry(intent)
    if existing:
        return existing

    settings = get_settings()
    context = build_reference_context(intent.reference_doctype, intent.reference_name)
    amount = flt(intent.amount_paid or intent.amount_requested)
    if amount <= 0:
        frappe.throw('Cannot create Payment Entry with zero amount')

    pe_doc = frappe.get_doc({
        'doctype': 'Payment Entry',
        'payment_type': 'Receive',
        'company': intent.company or settings.company,
        'posting_date': nowdate(),
        'party_type': 'Customer',
        'party': _resolve_customer(intent, context),
        'party_name': context.get('party_name'),
        'paid_amount': amount,
        'received_amount': amount,
        'paid_to': _resolve_paid_to_account(intent, settings),
        'reference_no': intent.provider_payment_id or intent.name,
        'reference_date': nowdate(),
        'remarks': f'Payment collected via {intent.provider} for {intent.reference_doctype} {intent.reference_name}',
        'mode_of_payment': (settings.pos_mode_of_payment if intent.request_channel == 'POS' else settings.default_mode_of_payment) or 'Razorpay',
        'reference_doctype': intent.reference_doctype,
        'reference_name': intent.reference_name,
        'created_by_agent': frappe.session.user,
    })

    if intent.sales_invoice and intent.request_type == 'Against Invoice':
        pe_doc.append('references', {
            'reference_doctype': 'Sales Invoice',
            'reference_name': intent.sales_invoice,
            'allocated_amount': min(amount, frappe.db.get_value('Sales Invoice', intent.sales_invoice, 'outstanding_amount') or amount),
            'total_amount': frappe.db.get_value('Sales Invoice', intent.sales_invoice, 'grand_total') or amount,
            'outstanding_amount': frappe.db.get_value('Sales Invoice', intent.sales_invoice, 'outstanding_amount') or amount,
        })

    pe_doc.insert(ignore_permissions=True)
    if settings.auto_create_payment_entry_on_success and settings.auto_submit_payment_entry:
        pe_doc.submit()
    return pe_doc.name


def allocate_available_amount(intent, payment_entry_name):
    intent.reload()
    remaining = flt(intent.amount_paid) - flt(intent.amount_allocated)
    if remaining <= 0:
        return 0

    allocated_total = 0
    for target in sorted(get_allocation_targets(intent), key=lambda x: x.get('priority', 99)):
        if remaining <= 0:
            break
        if target['doctype'] != 'Sales Invoice':
            continue
        outstanding = flt(frappe.db.get_value('Sales Invoice', target['name'], 'outstanding_amount') or 0)
        if outstanding <= 0:
            continue
        alloc = min(remaining, outstanding)
        if _allocation_exists(intent.name, target['doctype'], target['name']):
            continue
        allocation = frappe.get_doc({
            'doctype': 'Payment Allocation',
            'payment_intent': intent.name,
            'payment_entry': payment_entry_name,
            'allocated_amount': alloc,
            'target_doctype': target['doctype'],
            'target_name': target['name'],
            'allocation_date': frappe.utils.now_datetime(),
            'remarks': 'Auto allocation by Razorpay',
        })
        allocation.insert(ignore_permissions=True)
        remaining -= alloc
        allocated_total += alloc

    return allocated_total


def refresh_intent_and_reference(intent):
    allocated_total = flt(frappe.db.sql(
        "select coalesce(sum(allocated_amount),0) from `tabPayment Allocation` where payment_intent=%s and status!='Reversed'",
        intent.name,
    )[0][0])
    amount_paid = flt(intent.amount_paid or 0)
    unallocated = max(amount_paid - allocated_total, 0)

    status = 'Paid'
    allocation_status = 'Unallocated'
    if amount_paid <= 0:
        status = 'Requested'
    elif allocated_total > 0 and unallocated <= 0:
        status = 'Allocated'
        allocation_status = 'Fully Allocated'
    elif allocated_total > 0 and unallocated > 0:
        status = 'Partially Allocated'
        allocation_status = 'Partially Allocated'
    elif amount_paid > 0:
        allocation_status = 'Unallocated'

    intent.db_set('amount_allocated', allocated_total)
    intent.db_set('amount_unallocated', unallocated)
    intent.db_set('status', status)
    intent.db_set('allocation_status', allocation_status)
    update_reference_payment_summary(intent.reference_doctype, intent.reference_name)


def _existing_payment_entry(intent):
    keys = [k for k in [intent.provider_payment_id, intent.name] if k]
    if not keys:
        return None
    return frappe.db.get_value('Payment Entry', {'reference_no': ['in', keys]}, 'name')


def _resolve_customer(intent, context):
    settings = get_settings()
    if intent.reference_doctype in ('Sales Invoice', 'Sales Order') and context.get('party'):
        return context.get('party')
    if intent.reference_doctype == 'Patient Encounter':
        patient = intent.patient or context.get('patient')
        patient_name = context.get('party_name')
        if patient and frappe.db.exists('Customer', patient):
            return patient
        if patient_name:
            existing = frappe.db.get_value('Customer', {'customer_name': patient_name}, 'name')
            if existing:
                return existing
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': patient_name or patient or intent.reference_name,
            'customer_group': frappe.db.get_value('Customer Group', {}, 'name') or 'All Customer Groups',
            'territory': frappe.db.get_value('Territory', {}, 'name') or 'All Territories',
        })
        customer.insert(ignore_permissions=True)
        return customer.name
    if intent.reference_doctype == 'Lead' and settings.lead_auto_create_customer:
        lead_name = context.get('party_name') or intent.reference_name
        existing = frappe.db.get_value('Customer', {'customer_name': lead_name}, 'name')
        if existing:
            return existing
        customer = frappe.get_doc({
            'doctype': 'Customer',
            'customer_name': lead_name,
            'customer_group': frappe.db.get_value('Customer Group', {}, 'name') or 'All Customer Groups',
            'territory': frappe.db.get_value('Territory', {}, 'name') or 'All Territories',
        })
        customer.insert(ignore_permissions=True)
        return customer.name
    return context.get('party') or context.get('party_name')


def _resolve_paid_to_account(intent, settings):
    company = intent.company or settings.company
    account = settings.default_receivable_account
    if account:
        return account
    account = settings.default_advance_account
    if account:
        return account
    return frappe.get_value('Company', company, 'default_bank_account') or frappe.get_value('Company', company, 'default_cash_account')


def _allocation_exists(payment_intent, target_doctype, target_name):
    return frappe.db.exists('Payment Allocation', {
        'payment_intent': payment_intent,
        'target_doctype': target_doctype,
        'target_name': target_name,
        'status': ['!=', 'Reversed'],
    })


def _extract_payment_entity(payload):
    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity')
    if payment_entity:
        return payment_entity
    payment_entity = payload.get('payload', {}).get('pos_payment', {}).get('entity')
    if payment_entity:
        return payment_entity
    payment_entity = payload.get('payload', {}).get('payment_request', {}).get('entity', {}).get('payment')
    if payment_entity:
        return payment_entity
    payment_entity = payload.get('payload', {}).get('payment_request', {}).get('entity')
    if payment_entity:
        return payment_entity
    payment_link_entity = payload.get('payload', {}).get('payment_link', {}).get('entity', {})
    nested = payment_link_entity.get('payments') or []
    if nested:
        return nested[0]
    return {}


def _find_intent_by_provider_ids(payment_entity):
    notes = payment_entity.get('notes', {}) or {}
    if notes.get('payment_intent'):
        return notes.get('payment_intent')
    payment_link_id = payment_entity.get('payment_link_id')
    if payment_link_id:
        return frappe.db.get_value('Payment Intent', {'provider_link_id': payment_link_id}, 'name')
    pos_request_id = payment_entity.get('pos_request_id') or payment_entity.get('payment_request_id')
    if pos_request_id:
        return frappe.db.get_value('Payment Intent', {'provider_pos_request_id': pos_request_id}, 'name')
    order_id = payment_entity.get('order_id')
    if order_id:
        return frappe.db.get_value('Payment Intent', {'provider_order_id': order_id}, 'name')
    return None
