import hashlib

import frappe
from frappe.utils import cint, flt, now_datetime

from payment_orchestrator.api.common.validation import (
    ensure_payment_intent_action_permission,
    validate_patient_encounter_request,
)
from payment_orchestrator.logic import (
    allocate_available_amount,
    create_payment_entry_for_intent,
    process_provider_payment_success,
    refresh_intent_and_reference,
)
from payment_orchestrator.provider.pinelabs.online import PineLabsOnlineClient
from payment_orchestrator.provider.pinelabs.payment_link import PineLabsPaymentLinkAdapter
from payment_orchestrator.provider.pinelabs.pos import PineLabsPOSAdapter
from payment_orchestrator.services import create_payment_intent_doc, update_reference_payment_summary
from payment_orchestrator.utils import (
    as_json,
    ensure_mode_of_payment,
    get_flag,
    get_settings,
    is_doctype_enabled,
    is_pinelabs_payment_link_enabled,
    is_pinelabs_pos_enabled,
)


PAYMENT_ROLES = ("Accounts Manager", "Accounts User", "System Manager")


def _require_payment_role():
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not user_roles.intersection(PAYMENT_ROLES):
        frappe.throw("Not permitted to request Pine Labs payments", frappe.PermissionError)


@frappe.whitelist()
def create_payment_link(reference_doctype, reference_name, amount, request_type=None, request_channel=None, notes=None):
    _require_payment_role()
    amount = flt(amount)
    if amount <= 0:
        frappe.throw("Amount must be greater than zero")

    settings = get_settings()
    if not is_pinelabs_payment_link_enabled(settings=settings):
        frappe.throw("Pine Labs Payment Link is disabled in Payment Orchestrator Settings")

    from payment_orchestrator.api.common.validation import allow_partial, validate_reference_payment_request

    validate_reference_payment_request(reference_doctype, reference_name, amount, settings=settings)

    adapter = PineLabsPaymentLinkAdapter(settings=settings)
    adapter.ensure_available()

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel=request_channel or "Payment Link",
        notes=notes,
        gateway="Pine Labs",
        payment_mode="Payment Link",
    )

    context["allow_partial"] = allow_partial(settings, reference_doctype)
    adapter.create(intent, context)

    return {
        "payment_intent": intent.name,
        "gateway": intent.gateway,
        "payment_mode": intent.payment_mode,
        "payment_link_url": intent.payment_link_url,
        "provider_link_id": intent.provider_link_id,
        "status": intent.status,
        "provider_status": intent.payment_status,
    }


@frappe.whitelist()
def fetch_payment_link(payment_intent):
    _require_payment_role()
    intent = frappe.get_doc("Payment Intent", payment_intent)
    ensure_payment_intent_action_permission(intent)
    if intent.gateway != "Pine Labs":
        frappe.throw("Payment Intent is not a Pine Labs payment link")
    if not intent.provider_link_id:
        frappe.throw("Payment Intent has no provider link id")

    data = PineLabsOnlineClient(settings=get_settings()).get_payment_link(intent.provider_link_id)
    event = create_payment_link_event(
        data=data,
        intent=intent,
        event_type="pinelabs.payment_link.poll",
    )
    sync_payment_link(intent, data)
    intent.reload()
    result = None
    if is_payment_link_success(data) and not intent.amount_paid:
        result = process_provider_payment_success(
            payment_link_success_payload(data, intent),
            event_doc=event,
        )
        event.db_set("processing_status", "Processed")
        event.db_set("payment_entry", result.get("payment_entry"))
    elif is_payment_link_success(data) and intent.amount_paid:
        if not event.payment_entry:
            event.db_set("processing_status", "Duplicate")
    else:
        if not getattr(event.flags, "existing_provider_event", False):
            event.db_set("processing_status", "Processed")
    event.db_set("payment_intent", intent.name)
    return {
        "gateway": "Pine Labs",
        "payment_intent": intent.name,
        "provider_status": data.get("status"),
        "processed": bool(result),
        "result": result,
        "provider_response": data,
    }


def create_payment_link_event(data, intent=None, event_type="pinelabs.payment_link.status"):
    link_id = data.get("payment_link_id") or getattr(intent, "provider_link_id", None)
    order_id = data.get("order_id") or getattr(intent, "provider_order_id", None)
    status = data.get("status")
    intent_name = getattr(intent, "name", None) or data.get("merchant_payment_link_reference")
    guard_key = payment_link_guard_key(
        event_type=event_type,
        intent_name=intent_name,
        link_id=link_id,
        order_id=order_id,
        status=status,
    )
    existing_event_name = frappe.db.get_value(
        "Payment Provider Event",
        {
            "provider": "Pine Labs",
            "event_type": event_type,
            "duplicate_guard_key": guard_key,
        },
        "name",
    )
    if existing_event_name:
        event = frappe.get_doc("Payment Provider Event", existing_event_name)
        event.flags.existing_provider_event = True
        return event

    event = frappe.get_doc({
        "doctype": "Payment Provider Event",
        "provider": "Pine Labs",
        "event_type": event_type,
        "event_id": order_id or link_id,
        "verification_status": "Verified",
        "processing_status": "Pending",
        "duplicate_guard_key": guard_key,
        "payment_intent": intent_name if intent_name and frappe.db.exists("Payment Intent", intent_name) else None,
        "received_on": frappe.utils.now_datetime(),
        "payload": frappe.as_json(data),
    })
    event.insert(ignore_permissions=True)
    return event


def payment_link_guard_key(event_type, intent_name, link_id, order_id, status):
    guard_source = f"Pine Labs:{event_type}:{intent_name}:{link_id}:{order_id}:{status}"
    return hashlib.sha256(guard_source.encode("utf-8")).hexdigest()


def sync_payment_link(intent, data):
    updates = {
        "payment_status": data.get("status"),
        "provider_payload_snapshot": frappe.as_json(data),
        "last_synced_on": frappe.utils.now_datetime(),
    }
    if data.get("payment_link"):
        updates["payment_link_url"] = data.get("payment_link")
    if data.get("payment_link_id"):
        updates["provider_link_id"] = data.get("payment_link_id")
    if data.get("order_id"):
        updates["provider_order_id"] = data.get("order_id")
    if data.get("status") in ("EXPIRED", "CANCELLED"):
        updates["status"] = "Expired" if data.get("status") == "EXPIRED" else "Cancelled"
    frappe.db.set_value("Payment Intent", intent.name, updates, update_modified=False)


def is_payment_link_success(data):
    return (data.get("status") or "").upper() == "PROCESSED"


def payment_link_success_payload(data, intent):
    amount = data.get("amount") or {}
    metadata = data.get("merchant_metadata") or {}
    payment_intent = metadata.get("payment_intent") or data.get("merchant_payment_link_reference") or intent.name
    payment_id = data.get("order_id") or data.get("payment_link_id") or intent.provider_link_id

    return {
        "event": "payment_link.processed",
        "payload": {
            "payment_link": {
                "entity": {
                    "id": data.get("payment_link_id") or intent.provider_link_id,
                    "payment_id": payment_id,
                    "order_id": data.get("order_id"),
                    "amount": amount.get("value") or int(round(flt(intent.amount_requested) * 100)),
                    "amount_paid": amount.get("value") or int(round(flt(intent.amount_requested) * 100)),
                    "status": "paid",
                    "notes": {
                        "payment_intent": payment_intent,
                        "reference_doctype": metadata.get("reference_doctype") or intent.reference_doctype,
                        "reference_name": metadata.get("reference_name") or intent.reference_name,
                        "request_type": metadata.get("request_type") or intent.request_type,
                    },
                },
            },
        },
    }


@frappe.whitelist()
def get_pos_context():
    _require_payment_role()
    settings = get_settings()
    default_device = (
        getattr(settings, "default_pos_device_id", None)
        or getattr(settings, "pinelabs_client_id", None)
        or ""
    )
    return {
        "default_pos_device_id": default_device,
        "pinelabs_client_id": getattr(settings, "pinelabs_client_id", None),
        "pinelabs_store_id": getattr(settings, "pinelabs_store_id", None),
        "enable_pos_payments": bool(get_flag(settings, "enable_pos_payments")),
        "enable_pinelabs": bool(get_flag(settings, "enable_pinelabs", 1)),
        "enable_pinelabs_pos": is_pinelabs_pos_enabled(settings=settings),
    }


@frappe.whitelist()
def request_pos_payment(sales_invoice, amount=None, pos_device_id=None, notes=None, make_default=0, request_type=None):
    return request_pos_payment_from_reference(
        reference_doctype="Sales Invoice",
        reference_name=sales_invoice,
        amount=amount,
        pos_device_id=pos_device_id,
        notes=notes,
        make_default=make_default,
        request_type=request_type,
    )


@frappe.whitelist()
def request_pos_payment_from_reference(
    reference_doctype,
    reference_name,
    amount=None,
    pos_device_id=None,
    notes=None,
    make_default=0,
    pos_payment_method=None,
    request_type=None,
):
    _require_payment_role()
    settings = get_settings()
    if not is_pinelabs_pos_enabled(settings=settings):
        frappe.throw("Pine Labs POS is disabled in Payment Orchestrator Settings")

    if not is_doctype_enabled(reference_doctype):
        frappe.throw(f"Payment Orchestrator is disabled for {reference_doctype}")

    if not frappe.db.exists(reference_doctype, reference_name):
        frappe.throw(f"{reference_doctype} {reference_name} not found")

    reference_doc = frappe.get_doc(reference_doctype, reference_name)
    if not reference_doc.has_permission("read"):
        frappe.throw(f"Not permitted to access this {reference_doctype}", frappe.PermissionError)
    if reference_doctype == "Patient Encounter":
        validate_patient_encounter_request(reference_doc)

    request_type = resolve_pos_request_type(reference_doctype, request_type)
    invoice_name = resolve_pos_invoice(reference_doctype, reference_name) if request_type == "Against Invoice" else None
    if request_type == "Against Invoice" and not invoice_name:
        frappe.throw("Pine Labs POS Against Invoice needs a submitted Sales Invoice linked to this record")

    invoice = frappe.get_doc("Sales Invoice", invoice_name) if invoice_name else None
    if invoice:
        if invoice.docstatus != 1:
            frappe.throw("POS payment can be requested only for a submitted Sales Invoice")
        if not invoice.has_permission("read"):
            frappe.throw("Not permitted to access this Sales Invoice", frappe.PermissionError)

    outstanding = flt(getattr(invoice, "outstanding_amount", 0)) if invoice else 0
    amount = flt(amount or outstanding)
    if amount <= 0:
        frappe.throw("Amount must be greater than zero")
    if invoice and amount > outstanding and not getattr(settings, "allow_overpayment", 0):
        frappe.throw("Amount cannot be greater than invoice outstanding amount")

    client_id = pos_device_id or getattr(settings, "default_pos_device_id", None) or getattr(settings, "pinelabs_client_id", None)
    if not client_id:
        frappe.throw("Select a Pine Labs Client ID or set Client ID in Pine Labs settings")
    if cint(make_default) and pos_device_id:
        set_default_pos_device(pos_device_id)
        settings = get_settings()
    if not settings.pinelabs_merchant_id or not settings.get_password("pinelabs_security_token", raise_exception=False):
        frappe.throw("Pine Labs Merchant ID and Security Token are required")

    pos_payment_method, allowed_payment_mode = resolve_pos_payment_mode(settings, pos_payment_method)

    intent, context = create_payment_intent_doc(
        reference_doctype=reference_doctype,
        reference_name=reference_name,
        amount=amount,
        request_type=request_type,
        request_channel="POS",
        notes=notes,
        gateway="Pine Labs",
        payment_mode="POS",
    )
    if invoice and getattr(intent, "sales_invoice", None) != invoice.name:
        intent.db_set("sales_invoice", invoice.name)
        intent.reload()
    intent.db_set("provider_terminal_id", client_id)
    intent.db_set("pos_payment_method", pos_payment_method)
    intent.db_set("pos_allowed_payment_mode", allowed_payment_mode)
    intent.db_set("pos_request_status", "Requested")

    response, pos_request_id = PineLabsPOSAdapter(settings=settings).upload_transaction(
        intent,
        invoice or reference_doc,
        context,
        client_id,
        allowed_payment_mode=allowed_payment_mode,
    )
    if not _is_valid_pos_request_id(pos_request_id):
        failure_message = response.get("ResponseMessage") or response.get("Status") or "Pine Labs request failed"
        intent.db_set("provider_payload_snapshot", as_json(response))
        intent.db_set("pos_request_status", "Failed")
        intent.db_set("payment_status", failure_message)
        intent.db_set("pos_failure_reason", failure_message)
        frappe.throw(f"Pine Labs POS request failed: {failure_message}")

    return {
        "payment_intent": intent.name,
        "gateway": intent.gateway,
        "payment_mode": intent.payment_mode,
        "provider_pos_request_id": pos_request_id,
        "provider_order_id": None,
        "pos_request_status": frappe.db.get_value("Payment Intent", intent.name, "pos_request_status"),
        "amount": amount,
        "terminal_id": client_id,
        "pos_payment_method": pos_payment_method,
        "pos_allowed_payment_mode": allowed_payment_mode,
        "auto_cancel_duration": cint(settings.pinelabs_auto_cancel_duration or 5),
        "sales_invoice": invoice.name if invoice else None,
        "request_type": request_type,
        "reference_doctype": reference_doctype,
        "reference_name": reference_name,
    }


def resolve_pos_payment_mode(settings, pos_payment_method=None):
    method = (pos_payment_method or "All Modes").strip()
    normalized = method.lower().replace("_", " ").replace("-", " ")
    if normalized in {"all", "all modes", "any", "default"}:
        label = "All Modes"
        code = settings.pinelabs_allowed_payment_mode or "0"
    elif normalized in {"card", "cards"}:
        label = "Card"
        code = getattr(settings, "pinelabs_card_payment_mode_code", None)
    elif normalized in {"upi", "qr", "upi qr", "upi / qr", "upi/qr"}:
        label = "UPI / QR"
        code = getattr(settings, "pinelabs_upi_qr_payment_mode_code", None) or "10"
    else:
        frappe.throw("Invalid Pine Labs POS payment method")

    code = str(code or "").strip()
    if not code:
        frappe.throw(f"Set Pine Labs {label} Payment Mode Code in Payment Orchestrator Settings")
    return label, code


def resolve_pos_request_type(reference_doctype, request_type=None):
    request_type = request_type or ("Against Invoice" if reference_doctype == "Sales Invoice" else "Advance")
    if request_type not in {"Advance", "Against Invoice"}:
        frappe.throw("Invalid Pine Labs POS request type")
    if reference_doctype == "Sales Invoice" and request_type != "Against Invoice":
        frappe.throw("Sales Invoice POS payments can only be requested Against Invoice")
    if reference_doctype not in {"Patient Encounter", "Sales Invoice"}:
        frappe.throw("Pine Labs POS is available for Patient Encounter and Sales Invoice")
    return request_type


@frappe.whitelist()
def fetch_pos_payment_status(payment_intent):
    _require_payment_role()
    intent = frappe.get_doc("Payment Intent", payment_intent)
    ensure_payment_intent_action_permission(intent)
    if intent.request_channel != "POS":
        frappe.throw("Payment Intent is not a POS request")
    if not intent.provider_pos_request_id:
        frappe.throw("Payment Intent has no POS request id")

    settings = get_settings()
    if not is_pinelabs_pos_enabled(settings=settings):
        frappe.throw("Pine Labs POS is disabled in Payment Orchestrator Settings")
    response = PineLabsPOSAdapter(settings=settings).fetch_status(intent)
    if is_pos_approved(response) and not intent.provider_payment_id:
        apply_pos_success(intent, response)
    elif is_pos_terminal_failure(response):
        apply_pos_terminal_failure(intent, response)
    return {
        "payment_intent": intent.name,
        "gateway": frappe.db.get_value("Payment Intent", intent.name, "gateway"),
        "payment_mode": frappe.db.get_value("Payment Intent", intent.name, "payment_mode"),
        "pos_request_status": frappe.db.get_value("Payment Intent", intent.name, "pos_request_status"),
        "status": frappe.db.get_value("Payment Intent", intent.name, "status"),
        "failed": is_pos_terminal_failure(response),
        "failure_message": response.get("ResponseMessage") if is_pos_terminal_failure(response) else None,
        "provider_response": response,
    }


def is_pos_approved(response):
    return int(response.get("ResponseCode") or 0) == 0 and "APPROVED" in (response.get("ResponseMessage") or "").upper()


def is_pos_pending(response):
    message = (response.get("ResponseMessage") or "").upper()
    return int(response.get("ResponseCode") or 0) == 1001 or "UPLOADED" in message or "PENDING" in message


def is_pos_terminal_failure(response):
    if is_pos_approved(response) or is_pos_pending(response):
        return False
    return int(response.get("ResponseCode") or 0) != 0


def apply_pos_terminal_failure(intent, response):
    failure_message = response.get("ResponseMessage") or "Pine Labs POS transaction failed"
    try:
        frappe.flags.payment_orchestrator_system_update = True
        intent.db_set("payment_status", failure_message)
        intent.db_set("pos_request_status", failure_message)
        intent.db_set("pos_failure_reason", failure_message)
        intent.db_set("provider_payload_snapshot", as_json(response))
        if flt(intent.amount_paid or 0) <= 0:
            frappe.db.set_value(
                "Payment Intent",
                intent.name,
                {
                    "status": "Cancelled",
                    "amount_paid": 0,
                    "amount_allocated": 0,
                    "amount_unallocated": 0,
                    "allocation_status": "Unallocated",
                },
                update_modified=False,
            )
        update_reference_payment_summary(intent.reference_doctype, intent.reference_name)
        if getattr(intent, "sales_invoice", None):
            update_reference_payment_summary("Sales Invoice", intent.sales_invoice)
        publish_pos_failure(intent.name, failure_message)
    finally:
        frappe.flags.payment_orchestrator_system_update = False


def publish_pos_failure(payment_intent, message):
    try:
        requested_by = frappe.db.get_value("Payment Intent", payment_intent, "requested_by")
        frappe.publish_realtime(
            "payment_orchestrator_payment_failed",
            {
                "payment_intent": payment_intent,
                "status": frappe.db.get_value("Payment Intent", payment_intent, "status"),
                "message": message,
            },
            user=requested_by,
            after_commit=True,
        )
    except Exception:
        frappe.log_error(frappe.get_traceback(), f"POS failure realtime failed for {payment_intent}")


def _is_valid_pos_request_id(pos_request_id):
    try:
        return int(pos_request_id) > 0
    except Exception:
        return False


def apply_pos_success(intent, response):
    amount = pinelabs_amount(response) or flt(intent.amount_requested)
    settings = get_settings()
    if amount > flt(intent.amount_requested or 0) and not getattr(settings, "allow_overpayment", 0):
        frappe.throw("Provider payment amount is greater than requested amount")
    payment_id = str(response.get("PlutusTransactionReferenceID") or intent.provider_pos_request_id)
    ensure_mode_of_payment(getattr(settings, "pos_mode_of_payment", None) or "Pine Labs POS")
    intent.db_set("gateway", intent.gateway or "Pine Labs")
    intent.db_set("payment_mode", intent.payment_mode or "POS")
    intent.db_set("provider_payment_id", payment_id)
    intent.db_set("provider_event_id", payment_id)
    intent.db_set("payment_status", response.get("ResponseMessage") or "TXN APPROVED")
    intent.db_set("pos_request_status", response.get("ResponseMessage") or "TXN APPROVED")
    intent.db_set("amount_paid", amount)
    intent.db_set("amount_unallocated", amount)
    intent.db_set("paid_on", now_datetime())
    payment_entry = create_payment_entry_for_intent(intent)
    intent.db_set("payment_entry", payment_entry)
    allocate_available_amount(intent, payment_entry)
    refresh_intent_and_reference(intent)
    return payment_entry


def pinelabs_amount(response):
    for row in response.get("TransactionData") or []:
        if row.get("Tag") == "Amount":
            return flt(row.get("Value")) / 100
    if response.get("Amount"):
        return flt(response.get("Amount")) / 100
    return None


@frappe.whitelist()
def mock_pos_payment(reference_doctype, reference_name, amount=None, notes=None, pos_device_id=None, make_default=0):
    _require_payment_role()
    frappe.only_for(("System Manager",))
    if not is_doctype_enabled(reference_doctype):
        frappe.throw(f"Payment Orchestrator is disabled for {reference_doctype}")

    settings = get_settings()
    if not is_pinelabs_pos_enabled(settings=settings):
        frappe.throw("Pine Labs POS is disabled in Payment Orchestrator Settings")

    invoice_name = resolve_pos_invoice(reference_doctype, reference_name)
    if not invoice_name:
        frappe.throw("Demo POS payment needs a submitted Sales Invoice linked to this record")

    invoice = frappe.get_doc("Sales Invoice", invoice_name)
    outstanding = flt(getattr(invoice, "outstanding_amount", 0))
    amount = flt(amount or outstanding)
    if amount <= 0:
        frappe.throw("Amount must be greater than zero")
    if amount > outstanding and not getattr(settings, "allow_overpayment", 0):
        frappe.throw("Amount cannot be greater than invoice outstanding amount")

    intent, _context = create_payment_intent_doc(
        reference_doctype="Sales Invoice",
        reference_name=invoice.name,
        amount=amount,
        request_type="Against Invoice",
        request_channel="POS",
        notes=notes or "Demo POS payment",
        gateway="Pine Labs",
        payment_mode="POS",
    )

    mock_payment_id = f"mock_pos_{frappe.generate_hash(length=12)}"
    mock_request_id = f"mock_req_{frappe.generate_hash(length=12)}"
    if cint(make_default) and pos_device_id:
        set_default_pos_device(pos_device_id)
    terminal_id = pos_device_id or getattr(settings, "default_pos_device_id", None) or getattr(settings, "pinelabs_client_id", None) or "TEST_POS_DEVICE"
    payload = {
        "demo": True,
        "id": mock_payment_id,
        "payment_request_id": mock_request_id,
        "terminal_id": terminal_id,
        "amount": int(round(amount * 100)),
        "status": "captured",
        "notes": {"payment_intent": intent.name, "reference_name": invoice.name},
    }

    ensure_mode_of_payment(getattr(get_settings(), "pos_mode_of_payment", None) or "Pine Labs POS")
    intent.db_set("gateway", intent.gateway or "Pine Labs")
    intent.db_set("payment_mode", intent.payment_mode or "POS")
    intent.db_set("provider_payment_id", mock_payment_id)
    intent.db_set("provider_event_id", mock_payment_id)
    intent.db_set("provider_pos_request_id", mock_request_id)
    intent.db_set("provider_terminal_id", terminal_id)
    intent.db_set("payment_status", "captured")
    intent.db_set("pos_request_status", "captured")
    intent.db_set("amount_paid", amount)
    intent.db_set("amount_unallocated", amount)
    intent.db_set("paid_on", now_datetime())
    intent.db_set("provider_payload_snapshot", as_json(payload))

    payment_entry = create_payment_entry_for_intent(intent)
    refresh_intent_and_reference(intent)

    return {
        "payment_intent": intent.name,
        "payment_entry": payment_entry,
        "gateway": intent.gateway,
        "payment_mode": intent.payment_mode,
        "sales_invoice": invoice.name,
        "amount": amount,
        "terminal_id": terminal_id,
        "demo": True,
    }


def resolve_pos_invoice(reference_doctype, reference_name):
    if reference_doctype == "Sales Invoice":
        invoice = frappe.get_doc("Sales Invoice", reference_name)
        if invoice.docstatus != 1:
            frappe.throw("POS payment needs a submitted Sales Invoice")
        return invoice.name

    if reference_doctype != "Patient Encounter":
        return None

    meta = frappe.get_meta("Sales Invoice")
    for fieldname in ("patient_encounter", "custom_patient_encounter", "encounter"):
        if meta.get_field(fieldname):
            invoice = frappe.db.get_value(
                "Sales Invoice",
                {fieldname: reference_name, "docstatus": 1, "outstanding_amount": [">", 0]},
                "name",
                order_by="posting_date desc, creation desc",
            )
            if invoice:
                return invoice
    return None


def resolve_demo_invoice(reference_doctype, reference_name):
    return resolve_pos_invoice(reference_doctype, reference_name)


def set_default_pos_device(pos_device_id):
    frappe.only_for(("System Manager",))
    frappe.db.set_single_value("Payment Orchestrator Settings", "default_pos_device_id", pos_device_id)
    frappe.db.set_single_value("Payment Orchestrator Settings", "pinelabs_client_id", pos_device_id)
