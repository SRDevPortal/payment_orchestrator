import json
import hashlib
from urllib.parse import parse_qsl

import frappe

from razorpay_integration.logic import process_provider_payment_success
from razorpay_integration.api.pos import _apply_pinelabs_success
from razorpay_integration.utils import get_settings, now_ts, verify_razorpay_webhook_signature


@frappe.whitelist(allow_guest=True)
def razorpay_integration():
    payload = frappe.request.get_data(as_text=True) or '{}'
    signature = frappe.get_request_header('X-Razorpay-Signature')
    settings = get_settings()
    guard_key = hashlib.sha256(payload.encode('utf-8')).hexdigest()

    event = frappe.get_doc({
        'doctype': 'Payment Provider Event',
        'provider': settings.provider_name,
        'received_on': now_ts(),
        'payload': payload if settings.store_full_webhook_payload else '{}',
        'verification_status': 'Pending',
        'processing_status': 'Pending',
        'duplicate_guard_key': guard_key,
    })
    event.insert(ignore_permissions=True)

    if settings.enable_duplicate_webhook_guard and frappe.db.exists('Payment Provider Event', {
        'duplicate_guard_key': guard_key,
        'name': ['!=', event.name],
        'processing_status': ['in', ['Processed', 'Duplicate']],
    }):
        event.db_set('processing_status', 'Duplicate')
        return {'ok': True, 'duplicate': True}

    if not settings.enable_webhook_processing:
        event.db_set('processing_status', 'Ignored')
        event.db_set('error_message', 'Webhook processing disabled in settings')
        return {'ok': True, 'ignored': True}

    secret = settings.get_password('webhook_secret')
    if not verify_razorpay_webhook_signature(payload, signature, secret):
        event.db_set('verification_status', 'Rejected')
        event.db_set('processing_status', 'Failed')
        event.db_set('error_message', 'Invalid webhook signature')
        frappe.local.response['http_status_code'] = 400
        return {'ok': False, 'message': 'Invalid signature'}

    data = json.loads(payload)
    event.db_set('verification_status', 'Verified')
    event.db_set('event_type', data.get('event'))
    event.db_set('event_id', _resolve_event_id(data))

    try:
        result = _dispatch_event(data, event)
        if result.get('duplicate'):
            event.db_set('processing_status', 'Duplicate')
        else:
            event.db_set('processing_status', 'Processed')
        if result.get('payment_intent'):
            event.db_set('payment_intent', result.get('payment_intent'))
        if result.get('payment_entry'):
            event.db_set('payment_entry', result.get('payment_entry'))
        return {'ok': True, **result}
    except Exception:
        event.db_set('processing_status', 'Failed')
        event.db_set('error_message', frappe.get_traceback())
        raise


@frappe.whitelist(allow_guest=True)
def pinelabs():
    payload = frappe.request.get_data(as_text=True) or ''
    form = frappe.local.form_dict or {}
    data = dict(form) if form else dict(parse_qsl(payload.replace('\n', '&').replace('\r', '&')))
    settings = get_settings()
    guard_key = hashlib.sha256((payload or json.dumps(data, sort_keys=True)).encode('utf-8')).hexdigest()

    event = frappe.get_doc({
        'doctype': 'Payment Provider Event',
        'provider': settings.provider_name or 'Pine Labs',
        'received_on': now_ts(),
        'payload': payload or json.dumps(data, default=str),
        'verification_status': 'Verified',
        'processing_status': 'Pending',
        'duplicate_guard_key': guard_key,
        'event_type': 'pinelabs.postback',
        'event_id': data.get('PlutusTransactionReferenceID'),
    })
    event.insert(ignore_permissions=True)

    ptrid = data.get('PlutusTransactionReferenceID')
    intent_name = frappe.db.get_value('Payment Intent', {'provider_pos_request_id': ptrid}, 'name')
    if not intent_name:
        event.db_set('processing_status', 'Ignored')
        event.db_set('error_message', f'No Payment Intent found for PTRID {ptrid}')
        return {'ok': True, 'ignored': True}

    intent = frappe.get_doc('Payment Intent', intent_name)
    response = {
        'ResponseCode': int(data.get('ResponseCode') or 0),
        'ResponseMessage': data.get('ResponseMessage') or data.get('Status') or '',
        'PlutusTransactionReferenceID': ptrid,
        'Amount': data.get('Amount'),
        'TransactionData': [{'Tag': key, 'Value': value} for key, value in data.items()],
    }

    if response['ResponseCode'] == 0 and 'APPROVED' in response['ResponseMessage'].upper():
        payment_entry = _apply_pinelabs_success(intent, response)
        event.db_set('processing_status', 'Processed')
        event.db_set('payment_intent', intent.name)
        event.db_set('payment_entry', payment_entry)
        return {'ok': True, 'payment_intent': intent.name, 'payment_entry': payment_entry}

    intent.db_set('payment_status', response['ResponseMessage'])
    intent.db_set('pos_request_status', response['ResponseMessage'])
    intent.db_set('pos_failure_reason', response['ResponseMessage'])
    event.db_set('processing_status', 'Failed')
    event.db_set('payment_intent', intent.name)
    event.db_set('error_message', response['ResponseMessage'])
    return {'ok': True, 'payment_intent': intent.name, 'status': response['ResponseMessage']}


def _dispatch_event(data, event_doc):
    event_name = data.get('event')
    if event_name in ('payment_link.paid', 'payment.captured', 'pos.payment.captured', 'pos_payment.captured', 'payment_request.paid'):
        return process_provider_payment_success(data, event_doc=event_doc)
    if event_name in ('payment.failed', 'payment_link.cancelled', 'payment_link.expired', 'pos.payment.failed', 'pos_payment.failed', 'payment_request.failed', 'payment_request.cancelled'):
        return _mark_intent_status(data, event_name)
    if event_name in ('refund.processed', 'payment.refunded'):
        return _mark_refunded(data)
    return {'ignored': True, 'event': event_name}


def _mark_intent_status(data, event_name):
    payment_intent = _resolve_payment_intent(data)
    if not payment_intent:
        return {'ignored': True, 'event': event_name}
    if frappe.db.exists('Payment Intent', payment_intent):
        doc = frappe.get_doc('Payment Intent', payment_intent)
        mapped_status = {
            'payment.failed': 'Requested',
            'payment_link.cancelled': 'Cancelled',
            'payment_link.expired': 'Expired',
            'pos.payment.failed': 'Requested',
            'pos_payment.failed': 'Requested',
            'payment_request.failed': 'Requested',
            'payment_request.cancelled': 'Cancelled',
        }.get(event_name, doc.status)
        doc.db_set('status', mapped_status)
        doc.db_set('payment_status', event_name)
        if doc.request_channel == 'POS':
            doc.db_set('pos_request_status', event_name)
            if 'failed' in event_name:
                doc.db_set('pos_failure_reason', _extract_failure_reason(data))
        return {'payment_intent': doc.name, 'status': mapped_status}
    return {'ignored': True, 'event': event_name}


def _mark_refunded(data):
    payment_id = data.get('payload', {}).get('refund', {}).get('entity', {}).get('payment_id')
    intent_name = frappe.db.get_value('Payment Intent', {'provider_payment_id': payment_id}, 'name')
    if not intent_name:
        return {'ignored': True, 'event': 'refund'}
    doc = frappe.get_doc('Payment Intent', intent_name)
    doc.db_set('status', 'Refunded')
    doc.db_set('payment_status', 'refunded')
    return {'payment_intent': doc.name, 'status': 'Refunded'}


def _resolve_event_id(data):
    return (
        data.get('payload', {}).get('payment', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('payment_link', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('refund', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('payment_request', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('pos_payment', {}).get('entity', {}).get('id')
    )


def _resolve_payment_intent(data):
    entities = [
        data.get('payload', {}).get('payment', {}).get('entity', {}),
        data.get('payload', {}).get('payment_link', {}).get('entity', {}),
        data.get('payload', {}).get('payment_request', {}).get('entity', {}),
        data.get('payload', {}).get('pos_payment', {}).get('entity', {}),
    ]
    for entity in entities:
        notes = entity.get('notes', {}) or {}
        if notes.get('payment_intent'):
            return notes.get('payment_intent')

    payment_link_id = data.get('payload', {}).get('payment_link', {}).get('entity', {}).get('id')
    if payment_link_id:
        intent = frappe.db.get_value('Payment Intent', {'provider_link_id': payment_link_id}, 'name')
        if intent:
            return intent

    for entity in entities:
        pos_request_id = entity.get('pos_request_id') or entity.get('payment_request_id') or entity.get('id')
        if pos_request_id:
            intent = frappe.db.get_value('Payment Intent', {'provider_pos_request_id': pos_request_id}, 'name')
            if intent:
                return intent
        order_id = entity.get('order_id')
        if order_id:
            intent = frappe.db.get_value('Payment Intent', {'provider_order_id': order_id}, 'name')
            if intent:
                return intent
    return None


def _extract_failure_reason(data):
    payment = data.get('payload', {}).get('payment', {}).get('entity', {})
    error = payment.get('error_description') or payment.get('error_reason')
    if error:
        return error
    request = data.get('payload', {}).get('payment_request', {}).get('entity', {})
    return request.get('error_description') or request.get('error_reason') or data.get('event')
