import hashlib

import frappe

from payment_orchestrator.logic import process_provider_payment_success
from payment_orchestrator.provider.pinelabs.online import PineLabsOnlineClient
from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.utils import get_settings


@frappe.whitelist()
def fetch_payment_link(payment_intent):
    intent = frappe.get_doc('Payment Intent', payment_intent)
    if not intent.provider_link_id:
        frappe.throw('Payment Intent has no provider link id')

    settings = get_settings()
    if intent.gateway == 'Pine Labs':
        data = PineLabsOnlineClient(settings=settings).get_payment_link(intent.provider_link_id)
        event = create_pinelabs_payment_link_event(
            data=data,
            intent=intent,
            event_type='pinelabs.payment_link.poll',
        )
        _sync_pinelabs_payment_link(intent, data)
        intent.reload()
        result = None
        if _is_pinelabs_payment_link_success(data) and not intent.amount_paid:
            result = process_provider_payment_success(
                _pinelabs_payment_link_success_payload(data, intent),
                event_doc=event,
            )
            event.db_set('processing_status', 'Processed')
            event.db_set('payment_entry', result.get('payment_entry'))
        elif _is_pinelabs_payment_link_success(data) and intent.amount_paid:
            if not event.payment_entry:
                event.db_set('processing_status', 'Duplicate')
        else:
            if not getattr(event.flags, 'existing_provider_event', False):
                event.db_set('processing_status', 'Processed')
        event.db_set('payment_intent', intent.name)
        return {
            'gateway': 'Pine Labs',
            'payment_intent': intent.name,
            'provider_status': data.get('status'),
            'processed': bool(result),
            'result': result,
            'provider_response': data,
        }

    client = RazorpayClient(settings=settings, mode=intent.provider_mode or 'Test')
    data = client.fetch_payment_link(intent.provider_link_id)
    intent.db_set('payment_status', data.get('status'))
    intent.db_set('provider_payload_snapshot', frappe.as_json(data))
    return data


def create_pinelabs_payment_link_event(data, intent=None, event_type='pinelabs.payment_link.status'):
    link_id = data.get('payment_link_id') or getattr(intent, 'provider_link_id', None)
    order_id = data.get('order_id') or getattr(intent, 'provider_order_id', None)
    status = data.get('status')
    intent_name = getattr(intent, 'name', None) or data.get('merchant_payment_link_reference')
    guard_key = _pinelabs_payment_link_guard_key(
        event_type=event_type,
        intent_name=intent_name,
        link_id=link_id,
        order_id=order_id,
        status=status,
    )
    existing_event_name = frappe.db.get_value(
        'Payment Provider Event',
        {
            'provider': 'Pine Labs',
            'event_type': event_type,
            'duplicate_guard_key': guard_key,
        },
        'name',
    )
    if existing_event_name:
        event = frappe.get_doc('Payment Provider Event', existing_event_name)
        event.flags.existing_provider_event = True
        return event

    event = frappe.get_doc({
        'doctype': 'Payment Provider Event',
        'provider': 'Pine Labs',
        'event_type': event_type,
        'event_id': order_id or link_id,
        'verification_status': 'Verified',
        'processing_status': 'Pending',
        'duplicate_guard_key': guard_key,
        'payment_intent': intent_name if intent_name and frappe.db.exists('Payment Intent', intent_name) else None,
        'received_on': frappe.utils.now_datetime(),
        'payload': frappe.as_json(data),
    })
    event.insert(ignore_permissions=True)
    return event


def _pinelabs_payment_link_guard_key(event_type, intent_name, link_id, order_id, status):
    guard_source = f'Pine Labs:{event_type}:{intent_name}:{link_id}:{order_id}:{status}'
    return hashlib.sha256(guard_source.encode('utf-8')).hexdigest()


def _sync_pinelabs_payment_link(intent, data):
    updates = {
        'payment_status': data.get('status'),
        'provider_payload_snapshot': frappe.as_json(data),
        'last_synced_on': frappe.utils.now_datetime(),
    }
    if data.get('payment_link'):
        updates['payment_link_url'] = data.get('payment_link')
    if data.get('payment_link_id'):
        updates['provider_link_id'] = data.get('payment_link_id')
    if data.get('order_id'):
        updates['provider_order_id'] = data.get('order_id')
    if data.get('status') in ('EXPIRED', 'CANCELLED'):
        updates['status'] = 'Expired' if data.get('status') == 'EXPIRED' else 'Cancelled'
    frappe.db.set_value('Payment Intent', intent.name, updates, update_modified=False)


def _is_pinelabs_payment_link_success(data):
    return (data.get('status') or '').upper() == 'PROCESSED'


def _pinelabs_payment_link_success_payload(data, intent):
    amount = data.get('amount') or {}
    metadata = data.get('merchant_metadata') or {}
    payment_intent = metadata.get('payment_intent') or data.get('merchant_payment_link_reference') or intent.name
    payment_id = data.get('order_id') or data.get('payment_link_id') or intent.provider_link_id

    return {
        'event': 'payment_link.processed',
        'payload': {
            'payment_link': {
                'entity': {
                    'id': data.get('payment_link_id') or intent.provider_link_id,
                    'payment_id': payment_id,
                    'order_id': data.get('order_id'),
                    'amount': amount.get('value') or int(round(frappe.utils.flt(intent.amount_requested) * 100)),
                    'amount_paid': amount.get('value') or int(round(frappe.utils.flt(intent.amount_requested) * 100)),
                    'status': 'paid',
                    'notes': {
                        'payment_intent': payment_intent,
                        'reference_doctype': metadata.get('reference_doctype') or intent.reference_doctype,
                        'reference_name': metadata.get('reference_name') or intent.reference_name,
                        'request_type': metadata.get('request_type') or intent.request_type,
                    },
                },
            },
        },
    }


@frappe.whitelist()
def fetch_qr_code(payment_intent):
    intent = frappe.get_doc('Payment Intent', payment_intent)
    if not intent.provider_qr_id:
        frappe.throw('Payment Intent has no provider QR code id')
    client = RazorpayClient(settings=get_settings(), mode=intent.provider_mode or 'Test')
    data = client.fetch_qr_code(intent.provider_qr_id)
    intent.db_set('qr_status', data.get('status'))
    intent.db_set('payment_status', data.get('status'))
    intent.db_set('provider_payload_snapshot', frappe.as_json(data))
    return data


@frappe.whitelist()
def close_qr_code(payment_intent):
    intent = frappe.get_doc('Payment Intent', payment_intent)
    if not intent.provider_qr_id:
        frappe.throw('Payment Intent has no provider QR code id')
    client = RazorpayClient(settings=get_settings(), mode=intent.provider_mode or 'Test')
    data = client.close_qr_code(intent.provider_qr_id)
    intent.db_set('qr_status', data.get('status'))
    intent.db_set('payment_status', data.get('status'))
    intent.db_set('provider_payload_snapshot', frappe.as_json(data))
    return data


@frappe.whitelist()
def refund_payment(payment_intent, amount=None, notes=None):
    settings = get_settings()
    if not settings.enable_refunds:
        frappe.throw('Refunds are disabled in settings')
    intent = frappe.get_doc('Payment Intent', payment_intent)
    if not intent.provider_payment_id:
        frappe.throw('Payment has not been captured for this intent yet')
    payload = {}
    if amount:
        payload['amount'] = int(round(frappe.utils.flt(amount) * 100))
    if notes:
        payload['notes'] = {'reason': notes}
    client = RazorpayClient(settings=settings, mode=intent.provider_mode or 'Test')
    response = client.create_refund(intent.provider_payment_id, payload)
    intent.db_set('payment_status', 'refund_initiated')
    return response
