import json
import hashlib
from urllib.parse import parse_qsl

import frappe
from frappe.utils import escape_html

from payment_orchestrator.logic import process_provider_payment_success
from payment_orchestrator.api.pinelabs import (
    apply_pos_success as _apply_pinelabs_success,
    is_payment_link_success as _is_pinelabs_payment_link_success,
    payment_link_success_payload as _pinelabs_payment_link_success_payload,
    sync_payment_link as _sync_pinelabs_payment_link,
)
from payment_orchestrator.utils import (
    get_settings,
    is_pinelabs_postback_enabled,
    is_razorpay_webhook_enabled,
    now_ts,
    verify_razorpay_webhook_signature,
)


@frappe.whitelist(allow_guest=True)
def razorpay():
    payload = frappe.request.get_data(as_text=True) or '{}'
    signature = frappe.get_request_header('X-Razorpay-Signature')
    settings = get_settings()
    guard_key = hashlib.sha256(payload.encode('utf-8')).hexdigest()

    event = frappe.get_doc({
        'doctype': 'Payment Provider Event',
        'provider': 'Razorpay',
        'received_on': now_ts(),
        'payload': payload if settings.store_full_webhook_payload else '{}',
        'verification_status': 'Pending',
        'processing_status': 'Pending',
        'duplicate_guard_key': guard_key,
    })
    event.insert(ignore_permissions=True)
    frappe.db.commit()

    if settings.enable_duplicate_webhook_guard and frappe.db.exists('Payment Provider Event', {
        'duplicate_guard_key': guard_key,
        'name': ['!=', event.name],
        'processing_status': ['in', ['Processed', 'Duplicate']],
    }):
        event.db_set('processing_status', 'Duplicate')
        return {'ok': True, 'duplicate': True}

    if not is_razorpay_webhook_enabled(settings=settings):
        event.db_set('processing_status', 'Ignored')
        event.db_set('error_message', 'Razorpay webhook processing disabled in settings')
        return {'ok': True, 'ignored': True}

    secret = settings.get_password('webhook_secret')
    if not verify_razorpay_webhook_signature(payload, signature, secret):
        event.db_set('verification_status', 'Rejected')
        event.db_set('processing_status', 'Failed')
        event.db_set('error_message', 'Invalid webhook signature')
        frappe.db.commit()
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
        frappe.db.commit()
        raise


@frappe.whitelist(allow_guest=True)
def payment_orchestrator():
    return razorpay()


@frappe.whitelist(allow_guest=True)
def pinelabs():
    payload = frappe.request.get_data(as_text=True) or ''
    data = _parse_pinelabs_payload(payload)
    settings = get_settings()
    is_browser_callback = _is_browser_callback_request()
    guard_key = hashlib.sha256((payload or json.dumps(data, sort_keys=True)).encode('utf-8')).hexdigest()
    event_type = data.get('event') or ('pinelabs.payment_link.callback' if _is_pinelabs_payment_link_payload(data) else 'pinelabs.postback')

    event = frappe.get_doc({
        'doctype': 'Payment Provider Event',
        'provider': 'Pine Labs',
        'received_on': now_ts(),
        'payload': payload or json.dumps(data, default=str),
        'verification_status': 'Verified',
        'processing_status': 'Pending',
        'duplicate_guard_key': guard_key,
        'event_type': event_type,
        'event_id': _pinelabs_event_id(data),
    })
    event.insert(ignore_permissions=True)

    if not is_pinelabs_postback_enabled(settings=settings):
        event.db_set('processing_status', 'Ignored')
        event.db_set('error_message', 'Pine Labs postback processing disabled in settings')
        result = {'ok': True, 'ignored': True}
        return _pinelabs_browser_callback_response(result, data, is_browser_callback)

    if _is_pinelabs_payment_link_payload(data):
        result = _process_pinelabs_payment_link_event(data, event)
        return _pinelabs_browser_callback_response(result, data, is_browser_callback)

    ptrid = data.get('PlutusTransactionReferenceID')
    intent_name = frappe.db.get_value('Payment Intent', {'provider_pos_request_id': ptrid}, 'name')
    if not intent_name:
        event.db_set('processing_status', 'Ignored')
        event.db_set('error_message', f'No Payment Intent found for PTRID {ptrid}')
        result = {'ok': True, 'ignored': True}
        return _pinelabs_browser_callback_response(result, data, is_browser_callback)

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
        result = {'ok': True, 'payment_intent': intent.name, 'payment_entry': payment_entry}
        return _pinelabs_browser_callback_response(result, data, is_browser_callback)

    intent.db_set('payment_status', response['ResponseMessage'])
    intent.db_set('pos_request_status', response['ResponseMessage'])
    intent.db_set('pos_failure_reason', response['ResponseMessage'])
    event.db_set('processing_status', 'Failed')
    event.db_set('payment_intent', intent.name)
    event.db_set('error_message', response['ResponseMessage'])
    result = {'ok': True, 'payment_intent': intent.name, 'status': response['ResponseMessage']}
    return _pinelabs_browser_callback_response(result, data, is_browser_callback)


def _parse_pinelabs_payload(payload):
    if payload:
        try:
            data = json.loads(payload)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    form = frappe.local.form_dict or {}
    if form:
        return dict(form)
    return dict(parse_qsl((payload or '').replace('\n', '&').replace('\r', '&')))


def _is_browser_callback_request():
    if not getattr(frappe.local, 'request', None):
        return False

    if frappe.request.method == 'GET':
        return True

    accept_header = (frappe.get_request_header('Accept') or '').lower()
    content_type = (frappe.get_request_header('Content-Type') or '').lower()
    return 'text/html' in accept_header and 'application/json' not in content_type


def _pinelabs_browser_callback_response(result, data, is_browser_callback):
    if not is_browser_callback:
        return result

    if result.get('ignored'):
        title = 'Payment Update Pending'
        message = 'Payment callback received, but automatic Pine Labs postback processing is disabled.'
        indicator_color = 'orange'
    elif result.get('payment_entry') or result.get('duplicate'):
        title = 'Payment Received'
        message = 'Your payment has been received successfully.'
        indicator_color = 'green'
    else:
        title = 'Payment Status Updated'
        message = 'Your payment status has been updated.'
        indicator_color = 'blue'

    detail_rows = []
    payment_intent = result.get('payment_intent') or _pinelabs_callback_intent_name(data)
    if payment_intent:
        detail_rows.append(('Payment Intent', payment_intent))
    if result.get('payment_entry'):
        detail_rows.append(('Payment Entry', result.get('payment_entry')))
    if result.get('status'):
        detail_rows.append(('Status', result.get('status')))

    details_html = ''.join(
        f'<p><strong>{escape_html(label)}:</strong> {escape_html(str(value))}</p>'
        for label, value in detail_rows
        if value
    )
    html = f"""
        <div>
            <p>{escape_html(message)}</p>
            {details_html}
            <p class="text-muted small">You can close this window and return to the invoice.</p>
        </div>
        <script>
            setTimeout(function() {{
                if (window.opener) {{
                    window.close();
                }}
            }}, 2500);
        </script>
    """
    frappe.respond_as_web_page(
        title=title,
        html=html,
        indicator_color=indicator_color,
        primary_action='/',
        primary_label='Home',
        fullpage=True,
    )
    return None


def _pinelabs_callback_intent_name(data):
    source = data.get('data') if isinstance(data.get('data'), dict) else data
    intent_name = source.get('merchant_payment_link_reference')
    if intent_name and frappe.db.exists('Payment Intent', intent_name):
        return intent_name
    if source.get('payment_link_id'):
        return frappe.db.get_value('Payment Intent', {'provider_link_id': source.get('payment_link_id')}, 'name')
    if source.get('PlutusTransactionReferenceID'):
        return frappe.db.get_value(
            'Payment Intent',
            {'provider_pos_request_id': source.get('PlutusTransactionReferenceID')},
            'name',
        )
    return None


def _pinelabs_event_id(data):
    source = data.get('data') if isinstance(data.get('data'), dict) else data
    return (
        source.get('order_id')
        or source.get('payment_link_id')
        or source.get('PlutusTransactionReferenceID')
        or source.get('merchant_payment_link_reference')
    )


def _is_pinelabs_payment_link_payload(data):
    source = data.get('data') if isinstance(data.get('data'), dict) else data
    event_name = data.get('event') or ''
    return bool(
        event_name.startswith('payment_link.')
        or source.get('payment_link_id')
        or source.get('merchant_payment_link_reference')
    )


def _process_pinelabs_payment_link_event(data, event):
    link_data = _normalize_pinelabs_payment_link_event(data)
    intent_name = (
        link_data.get('merchant_payment_link_reference')
        or frappe.db.get_value('Payment Intent', {'provider_link_id': link_data.get('payment_link_id')}, 'name')
    )
    if not intent_name or not frappe.db.exists('Payment Intent', intent_name):
        event.db_set('processing_status', 'Ignored')
        event.db_set('error_message', 'No Payment Intent found for Pine Labs payment link event')
        return {'ok': True, 'ignored': True}

    intent = frappe.get_doc('Payment Intent', intent_name)
    _sync_pinelabs_payment_link(intent, link_data)
    intent.reload()
    event.db_set('payment_intent', intent.name)

    if _is_pinelabs_payment_link_success(link_data):
        if intent.amount_paid:
            event.db_set('processing_status', 'Duplicate')
            return {'ok': True, 'duplicate': True, 'payment_intent': intent.name}
        result = process_provider_payment_success(
            _pinelabs_payment_link_success_payload(link_data, intent),
            event_doc=event,
        )
        event.db_set('processing_status', 'Processed')
        event.db_set('payment_entry', result.get('payment_entry'))
        return {'ok': True, **result}

    status = (link_data.get('status') or '').upper()
    if status in ('FAILED', 'CANCELLED', 'EXPIRED'):
        mapped_status = 'Cancelled' if status == 'CANCELLED' else ('Expired' if status == 'EXPIRED' else 'Requested')
        intent.db_set('status', mapped_status)
        intent.db_set('payment_status', status)
        event.db_set('processing_status', 'Failed' if status == 'FAILED' else 'Processed')
        event.db_set('error_message', status if status == 'FAILED' else None)
        return {'ok': True, 'payment_intent': intent.name, 'status': mapped_status}

    event.db_set('processing_status', 'Processed')
    return {'ok': True, 'payment_intent': intent.name, 'status': link_data.get('status')}


def _normalize_pinelabs_payment_link_event(data):
    source = data.get('data') if isinstance(data.get('data'), dict) else data
    metadata = source.get('merchant_metadata') if isinstance(source.get('merchant_metadata'), dict) else {}
    amount = source.get('amount') if isinstance(source.get('amount'), dict) else {'value': source.get('amount'), 'currency': source.get('currency') or 'INR'}
    return {
        'payment_link': source.get('payment_link'),
        'payment_link_id': source.get('payment_link_id'),
        'status': source.get('status'),
        'amount': amount,
        'amount_due': source.get('amount_due') if isinstance(source.get('amount_due'), dict) else None,
        'order_id': source.get('order_id'),
        'merchant_payment_link_reference': source.get('merchant_payment_link_reference'),
        'merchant_metadata': metadata,
    }


def _dispatch_event(data, event_doc):
    event_name = data.get('event')
    if event_name in ('payment_link.paid', 'payment.captured', 'qr_code.credited', 'pos.payment.captured', 'pos_payment.captured', 'payment_request.paid'):
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
        or data.get('payload', {}).get('qr_code', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('refund', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('payment_request', {}).get('entity', {}).get('id')
        or data.get('payload', {}).get('pos_payment', {}).get('entity', {}).get('id')
    )


def _resolve_payment_intent(data):
    entities = [
        data.get('payload', {}).get('payment', {}).get('entity', {}),
        data.get('payload', {}).get('payment_link', {}).get('entity', {}),
        data.get('payload', {}).get('qr_code', {}).get('entity', {}),
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

    qr_code_id = data.get('payload', {}).get('qr_code', {}).get('entity', {}).get('id')
    if qr_code_id:
        intent = frappe.db.get_value('Payment Intent', {'provider_qr_id': qr_code_id}, 'name')
        if intent:
            return intent

    for entity in entities:
        qr_code_id = entity.get('qr_code_id') or entity.get('qr_code')
        if qr_code_id:
            intent = frappe.db.get_value('Payment Intent', {'provider_qr_id': qr_code_id}, 'name')
            if intent:
                return intent
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
