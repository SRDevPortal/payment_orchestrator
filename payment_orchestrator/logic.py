import frappe
from frappe.utils import flt, getdate, nowdate

from payment_orchestrator.services import (
    build_reference_context,
    get_allocation_targets,
    update_reference_payment_summary,
)
from payment_orchestrator.utils import as_json, get_settings


def process_provider_payment_success(payload, event_doc=None):
    payment_entity = _extract_payment_entity(payload)
    notes = payment_entity.get('notes', {}) or {}
    payment_intent_name = notes.get('payment_intent') or _find_intent_by_provider_ids(payment_entity)
    if not payment_intent_name:
        frappe.throw('Unable to resolve Payment Intent from webhook payload')

    intent = frappe.get_doc('Payment Intent', payment_intent_name)
    if intent.provider_payment_id and intent.provider_payment_id == payment_entity.get('id'):
        if intent.reference_doctype == 'Patient Encounter':
            sync_encounter_multi_payment_from_intent(intent)
            refresh_intent_and_reference(intent)
            _publish_payment_completion(intent, None, 0)
            return {'payment_intent': intent.name, 'payment_entry': None, 'duplicate': True}
        existing_pe = _existing_payment_entry(intent)
        if existing_pe:
            _publish_payment_completion(intent, existing_pe, 0)
            return {'payment_intent': intent.name, 'payment_entry': existing_pe, 'duplicate': True}

    amount_paid = flt(payment_entity.get('amount') or payment_entity.get('amount_paid') or 0) / 100
    if amount_paid <= 0 and payment_entity.get('status') in ('paid', 'captured'):
        amount_paid = flt(intent.amount_requested or 0)
    settings = get_settings()
    if amount_paid > flt(intent.amount_requested or 0) and not getattr(settings, 'allow_overpayment', 0):
        frappe.throw('Provider payment amount is greater than requested amount')

    intent.db_set('provider_payment_id', payment_entity.get('id'))
    intent.db_set('gateway', intent.gateway or ('Pine Labs' if intent.request_channel == 'POS' else 'Razorpay'))
    intent.db_set('payment_mode', intent.payment_mode or ('POS' if intent.request_channel == 'POS' else 'Payment Link'))
    intent.db_set('provider_event_id', payment_entity.get('id'))
    intent.db_set('provider_pos_request_id', payment_entity.get('pos_request_id') or payment_entity.get('payment_request_id') or intent.provider_pos_request_id)
    intent.db_set('provider_order_id', payment_entity.get('order_id') or intent.provider_order_id)
    intent.db_set('provider_qr_id', payment_entity.get('qr_code_id') or payment_entity.get('qr_code') or intent.provider_qr_id)
    intent.db_set('provider_terminal_id', payment_entity.get('terminal_id') or payment_entity.get('device_id') or intent.provider_terminal_id)
    intent.db_set('payment_status', payment_entity.get('status'))
    if intent.request_channel == 'POS':
        intent.db_set('pos_request_status', payment_entity.get('status') or 'paid')
    intent.db_set('amount_paid', amount_paid)
    intent.db_set('amount_unallocated', amount_paid)
    intent.db_set('paid_on', frappe.utils.now_datetime())
    intent.db_set('provider_payload_snapshot', as_json(payload))

    intent.reload()
    if intent.reference_doctype == 'Patient Encounter':
        sync_encounter_multi_payment_from_intent(intent)
        refresh_intent_and_reference(intent)
        _publish_payment_completion(intent, None, 0)
        return {
            'payment_intent': intent.name,
            'payment_entry': None,
            'allocated_amount': 0,
            'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
        }

    payment_entry_name = create_payment_entry_for_intent(intent)
    allocated_amount = 0
    if settings.enable_auto_allocation:
        allocated_amount = allocate_available_amount(intent, payment_entry_name)

    refresh_intent_and_reference(intent)
    _publish_payment_completion(intent, payment_entry_name, allocated_amount)

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

    created_by_agent = _session_user()

    def create_entry():
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
            'mode_of_payment': _resolve_mode_of_payment(intent, settings),
            'reference_doctype': intent.reference_doctype,
            'reference_name': intent.reference_name,
            'created_by_agent': created_by_agent,
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

    return _run_as_system_user_for_guest(create_entry)


def _publish_payment_completion(intent, payment_entry_name=None, allocated_amount=0):
    try:
        frappe.publish_realtime(
            'payment_orchestrator_payment_completed',
            {
                'payment_intent': intent.name,
                'payment_entry': payment_entry_name,
                'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
                'amount_paid': flt(intent.amount_paid or 0),
                'allocated_amount': allocated_amount,
            },
            user=intent.requested_by,
            after_commit=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f'Payment completion realtime failed for {intent.name}')


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


def apply_unpaid_terminal_provider_status(intent, provider_status=None, provider_payload=None):
    if flt(getattr(intent, 'amount_paid', 0) or 0) > 0:
        return None

    status = (provider_status or '').strip().lower()
    mapped_status = None
    if status in {'closed', 'expired'}:
        mapped_status = 'Expired'
    elif status in {'cancelled', 'canceled', 'failed'}:
        mapped_status = 'Cancelled'

    if not mapped_status:
        return None

    updates = {
        'status': mapped_status,
        'payment_status': provider_status,
        'amount_paid': 0,
        'amount_allocated': 0,
        'amount_unallocated': 0,
        'allocation_status': 'Unallocated',
        'last_synced_on': frappe.utils.now_datetime(),
    }
    if provider_payload is not None:
        updates['provider_payload_snapshot'] = as_json(provider_payload)
    if getattr(intent, 'payment_mode', None) == 'QR Code':
        updates['qr_status'] = provider_status

    frappe.db.set_value('Payment Intent', intent.name, updates, update_modified=False)
    update_reference_payment_summary(intent.reference_doctype, intent.reference_name)
    if getattr(intent, 'sales_invoice', None):
        update_reference_payment_summary('Sales Invoice', intent.sales_invoice)
    return mapped_status


def sync_encounter_multi_payment_from_intent(intent):
    if intent.reference_doctype != 'Patient Encounter' or not intent.reference_name:
        return None
    if not frappe.db.exists('Patient Encounter', intent.reference_name):
        return None

    encounter = frappe.get_doc('Patient Encounter', intent.reference_name)
    if not frappe.get_meta('Patient Encounter').get_field('enc_multi_payments'):
        return None

    row = _find_encounter_payment_row(encounter, intent)
    paid_on = getdate(intent.paid_on) if intent.paid_on else nowdate()
    reference_no = _provider_reference_no(intent)
    values = {
        'mmp_paid_amount': flt(intent.amount_paid or intent.amount_requested),
        'mmp_mode_of_payment': _resolve_mode_of_payment(intent, get_settings()),
        'mmp_reference_no': reference_no,
        'mmp_reference_date': paid_on,
        'mmp_payment_intent': intent.name,
        'mmp_provider_payment_id': intent.provider_payment_id or reference_no,
        'mmp_gateway': intent.gateway,
        'mmp_payment_mode': intent.payment_mode,
        'mmp_orchestrator_status': 'Paid',
    }
    values = _filter_values_for_doctype('SR Multi Mode Payment', values)

    if row is not None:
        frappe.db.set_value('SR Multi Mode Payment', row.name, values, update_modified=False)
        return row.name

    next_idx = max([flt(getattr(item, 'idx', 0)) for item in getattr(encounter, 'enc_multi_payments', []) or []] or [0]) + 1
    row = frappe.get_doc({
        'doctype': 'SR Multi Mode Payment',
        'parent': encounter.name,
        'parenttype': 'Patient Encounter',
        'parentfield': 'enc_multi_payments',
        'idx': next_idx,
        **values,
    })
    row.insert(ignore_permissions=True)
    frappe.db.set_value('Patient Encounter', encounter.name, 'modified', frappe.utils.now(), update_modified=False)
    return row.name


def link_encounter_billing_result(payment_intent, sales_invoice=None, payment_entry=None, allocated_amount=0):
    if not payment_intent or not frappe.db.exists('Payment Intent', payment_intent):
        return None

    intent = frappe.get_doc('Payment Intent', payment_intent)
    updates = {}
    meta = frappe.get_meta('Payment Intent')
    if sales_invoice and meta.get_field('sales_invoice'):
        updates['sales_invoice'] = sales_invoice
    if payment_entry and meta.get_field('payment_entry'):
        updates['payment_entry'] = payment_entry
    if updates:
        frappe.db.set_value('Payment Intent', intent.name, updates, update_modified=False)

    alloc_amount = flt(allocated_amount or intent.amount_paid or 0)
    if sales_invoice and payment_entry and alloc_amount > 0:
        _upsert_payment_allocation(intent.name, payment_entry, sales_invoice, alloc_amount)

    intent.reload()
    refresh_intent_and_reference(intent)
    if sales_invoice:
        update_reference_payment_summary('Sales Invoice', sales_invoice)
    return {
        'payment_intent': intent.name,
        'sales_invoice': sales_invoice,
        'payment_entry': payment_entry,
        'allocated_amount': alloc_amount,
        'status': frappe.db.get_value('Payment Intent', intent.name, 'status'),
    }


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
    if intent.reference_doctype == 'CRM Lead' and getattr(settings, 'crm_lead_auto_create_customer', 1):
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


def _resolve_mode_of_payment(intent, settings):
    if intent.request_channel == 'POS':
        mode = settings.pos_mode_of_payment or 'Pine Labs POS'
    elif intent.gateway == 'Pine Labs':
        mode = 'Pine Labs'
    else:
        mode = settings.default_mode_of_payment or 'Razorpay'
    if not frappe.db.exists('Mode of Payment', mode):
        frappe.get_doc({
            'doctype': 'Mode of Payment',
            'mode_of_payment': mode,
            'enabled': 1,
        }).insert(ignore_permissions=True)
    return mode


def _session_user():
    return getattr(frappe.session, 'user', None) or 'Administrator'


def _run_as_system_user_for_guest(callback):
    original_user = _session_user()
    if original_user != 'Guest':
        return callback()

    frappe.set_user('Administrator')
    try:
        return callback()
    finally:
        frappe.set_user(original_user)


def _allocation_exists(payment_intent, target_doctype, target_name):
    return frappe.db.exists('Payment Allocation', {
        'payment_intent': payment_intent,
        'target_doctype': target_doctype,
        'target_name': target_name,
        'status': ['!=', 'Reversed'],
    })


def _find_encounter_payment_row(encounter, intent):
    reference_no = _provider_reference_no(intent)
    for row in getattr(encounter, 'enc_multi_payments', []) or []:
        if getattr(row, 'mmp_payment_intent', None) == intent.name:
            return row
        if intent.provider_payment_id and getattr(row, 'mmp_provider_payment_id', None) == intent.provider_payment_id:
            return row
        if reference_no and getattr(row, 'mmp_reference_no', None) == reference_no:
            return row
    return None


def _provider_reference_no(intent):
    return (
        intent.provider_payment_id
        or intent.provider_order_id
        or intent.provider_pos_request_id
        or intent.provider_qr_id
        or intent.provider_link_id
        or intent.name
    )


def _set_child_values_if_present(row, child_doctype, values):
    meta = frappe.get_meta(child_doctype)
    for fieldname, value in values.items():
        if meta.get_field(fieldname):
            setattr(row, fieldname, value)


def _filter_values_for_doctype(doctype, values):
    meta = frappe.get_meta(doctype)
    return {
        fieldname: value
        for fieldname, value in values.items()
        if meta.get_field(fieldname)
    }


def _upsert_payment_allocation(payment_intent, payment_entry, sales_invoice, allocated_amount):
    existing = frappe.db.get_value('Payment Allocation', {
        'payment_intent': payment_intent,
        'target_doctype': 'Sales Invoice',
        'target_name': sales_invoice,
        'status': ['!=', 'Reversed'],
    }, 'name')
    values = {
        'payment_entry': payment_entry,
        'allocated_amount': allocated_amount,
        'status': 'Allocated',
        'allocation_date': frappe.utils.now_datetime(),
        'remarks': 'Linked from Patient Encounter billing',
    }
    if existing:
        frappe.db.set_value('Payment Allocation', existing, values, update_modified=False)
        return existing

    allocation = frappe.get_doc({
        'doctype': 'Payment Allocation',
        'status': 'Allocated',
        'payment_intent': payment_intent,
        'payment_entry': payment_entry,
        'allocated_amount': allocated_amount,
        'target_doctype': 'Sales Invoice',
        'target_name': sales_invoice,
        'allocation_date': frappe.utils.now_datetime(),
        'remarks': 'Linked from Patient Encounter billing',
    })
    allocation.insert(ignore_permissions=True)
    return allocation.name


def _extract_payment_entity(payload):
    payment_entity = payload.get('payload', {}).get('payment', {}).get('entity')
    if payment_entity:
        qr_code_entity = payload.get('payload', {}).get('qr_code', {}).get('entity')
        if qr_code_entity:
            payment_entity = dict(payment_entity)
            if qr_code_entity.get('id') and not payment_entity.get('qr_code_id'):
                payment_entity['qr_code_id'] = qr_code_entity.get('id')
            if qr_code_entity.get('notes') and not (payment_entity.get('notes') or {}).get('payment_intent'):
                payment_entity['notes'] = qr_code_entity.get('notes')
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
        payment = dict(nested[0])
        return _merge_payment_link_context(payment, payment_link_entity)
    if payment_link_entity:
        return _payment_entity_from_payment_link(payment_link_entity)
    return {}


def _merge_payment_link_context(payment, payment_link_entity):
    if payment_link_entity.get('id') and not payment.get('payment_link_id'):
        payment['payment_link_id'] = payment_link_entity.get('id')
    if payment_link_entity.get('notes') and not payment.get('notes'):
        payment['notes'] = payment_link_entity.get('notes')
    if not payment.get('amount') and payment_link_entity.get('amount_paid'):
        payment['amount'] = payment_link_entity.get('amount_paid')
    if not payment.get('amount') and payment_link_entity.get('amount'):
        payment['amount'] = payment_link_entity.get('amount')
    return payment


def _payment_entity_from_payment_link(payment_link_entity):
    payment_id = (
        payment_link_entity.get('payment_id')
        or payment_link_entity.get('razorpay_payment_id')
        or payment_link_entity.get('id')
    )
    return {
        'id': payment_id,
        'payment_link_id': payment_link_entity.get('id'),
        'order_id': payment_link_entity.get('order_id'),
        'amount': payment_link_entity.get('amount_paid') or payment_link_entity.get('amount') or 0,
        'status': payment_link_entity.get('status'),
        'notes': payment_link_entity.get('notes') or {},
    }


def _find_intent_by_provider_ids(payment_entity):
    notes = payment_entity.get('notes', {}) or {}
    if notes.get('payment_intent'):
        return notes.get('payment_intent')
    payment_link_id = payment_entity.get('payment_link_id')
    if not payment_link_id and str(payment_entity.get('id') or '').startswith('plink_'):
        payment_link_id = payment_entity.get('id')
    if payment_link_id:
        return frappe.db.get_value('Payment Intent', {'provider_link_id': payment_link_id}, 'name')
    qr_code_id = payment_entity.get('qr_code_id') or payment_entity.get('qr_code')
    if not qr_code_id and str(payment_entity.get('id') or '').startswith('qr_'):
        qr_code_id = payment_entity.get('id')
    if qr_code_id:
        return frappe.db.get_value('Payment Intent', {'provider_qr_id': qr_code_id}, 'name')
    pos_request_id = payment_entity.get('pos_request_id') or payment_entity.get('payment_request_id')
    if pos_request_id:
        return frappe.db.get_value('Payment Intent', {'provider_pos_request_id': pos_request_id}, 'name')
    order_id = payment_entity.get('order_id')
    if order_id:
        return frappe.db.get_value('Payment Intent', {'provider_order_id': order_id}, 'name')
    return None
