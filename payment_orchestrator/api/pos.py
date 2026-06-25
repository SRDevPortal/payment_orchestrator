import frappe
from frappe.utils import cint, flt, now_datetime

from payment_orchestrator.logic import create_payment_entry_for_intent, refresh_intent_and_reference
from payment_orchestrator.provider.pinelabs.pos import PineLabsPOSAdapter
from payment_orchestrator.services import create_payment_intent_doc
from payment_orchestrator.utils import as_json, get_flag, get_settings, is_doctype_enabled, is_pinelabs_pos_enabled


PAYMENT_ROLES = ("Accounts Manager", "Accounts User", "System Manager")


def _require_payment_role():
    user_roles = set(frappe.get_roles(frappe.session.user))
    if not user_roles.intersection(PAYMENT_ROLES):
        frappe.throw("Not permitted to request POS payments", frappe.PermissionError)


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
def request_pos_payment(sales_invoice, amount=None, pos_device_id=None, notes=None, make_default=0):
    _require_payment_role()
    settings = get_settings()
    if not is_pinelabs_pos_enabled(settings=settings):
        frappe.throw("Pine Labs POS is disabled in Payment Orchestrator Settings")

    invoice = frappe.get_doc("Sales Invoice", sales_invoice)
    if invoice.docstatus != 1:
        frappe.throw("POS payment can be requested only for a submitted Sales Invoice")
    if not invoice.has_permission("read"):
        frappe.throw("Not permitted to access this Sales Invoice", frappe.PermissionError)

    outstanding = flt(getattr(invoice, "outstanding_amount", 0))
    amount = flt(amount or outstanding)
    if amount <= 0:
        frappe.throw("Amount must be greater than zero")
    if amount > outstanding and not getattr(settings, "allow_overpayment", 0):
        frappe.throw("Amount cannot be greater than invoice outstanding amount")

    client_id = pos_device_id or getattr(settings, "default_pos_device_id", None) or getattr(settings, "pinelabs_client_id", None)
    if not client_id:
        frappe.throw("Select a Pine Labs Client ID or set Client ID in Pine Labs settings")
    if cint(make_default) and pos_device_id:
        _set_default_pos_device(pos_device_id)
        settings = get_settings()
    if not settings.pinelabs_merchant_id or not settings.get_password("pinelabs_security_token", raise_exception=False):
        frappe.throw("Pine Labs Merchant ID and Security Token are required")

    intent, context = create_payment_intent_doc(
        reference_doctype="Sales Invoice",
        reference_name=invoice.name,
        amount=amount,
        request_type="Against Invoice",
        request_channel="POS",
        notes=notes,
        gateway="Pine Labs",
        payment_mode="POS",
    )
    intent.db_set("provider_terminal_id", client_id)
    intent.db_set("pos_request_status", "Requested")

    response, pos_request_id = PineLabsPOSAdapter(settings=settings).upload_transaction(intent, invoice, context, client_id)
    if not pos_request_id or int(pos_request_id or 0) == 0:
        intent.db_set("pos_request_status", "Failed")
        intent.db_set("pos_failure_reason", response.get("ResponseMessage") or "Pine Labs request failed")
        frappe.throw(response.get("ResponseMessage") or "Pine Labs did not return a transaction reference ID")

    return {
        "payment_intent": intent.name,
        "gateway": intent.gateway,
        "payment_mode": intent.payment_mode,
        "provider_pos_request_id": pos_request_id,
        "provider_order_id": None,
        "pos_request_status": frappe.db.get_value("Payment Intent", intent.name, "pos_request_status"),
        "amount": amount,
        "terminal_id": client_id,
    }


@frappe.whitelist()
def fetch_pos_payment_status(payment_intent):
    _require_payment_role()
    intent = frappe.get_doc("Payment Intent", payment_intent)
    if intent.request_channel != "POS":
        frappe.throw("Payment Intent is not a POS request")
    if not intent.provider_pos_request_id:
        frappe.throw("Payment Intent has no POS request id")

    settings = get_settings()
    if not is_pinelabs_pos_enabled(settings=settings):
        frappe.throw("Pine Labs POS is disabled in Payment Orchestrator Settings")
    response = PineLabsPOSAdapter(settings=settings).fetch_status(intent)
    if _is_pinelabs_approved(response) and not intent.provider_payment_id:
        _apply_pinelabs_success(intent, response)
    return {
        "payment_intent": intent.name,
        "gateway": frappe.db.get_value("Payment Intent", intent.name, "gateway"),
        "payment_mode": frappe.db.get_value("Payment Intent", intent.name, "payment_mode"),
        "pos_request_status": frappe.db.get_value("Payment Intent", intent.name, "pos_request_status"),
        "provider_response": response,
    }


def _is_pinelabs_approved(response):
    return int(response.get("ResponseCode") or 0) == 0 and "APPROVED" in (response.get("ResponseMessage") or "").upper()


def _apply_pinelabs_success(intent, response):
    amount = _pinelabs_amount(response) or flt(intent.amount_requested)
    payment_id = str(response.get("PlutusTransactionReferenceID") or intent.provider_pos_request_id)
    _ensure_mode_of_payment(getattr(get_settings(), "pos_mode_of_payment", None) or "Pine Labs POS")
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
    refresh_intent_and_reference(intent)
    return payment_entry


def _pinelabs_amount(response):
    for row in response.get("TransactionData") or []:
        if row.get("Tag") == "Amount":
            return flt(row.get("Value")) / (100 if flt(row.get("Value")) > 1000 else 1)
    if response.get("Amount"):
        return flt(response.get("Amount")) / 100
    return None


@frappe.whitelist()
def mock_pos_payment(reference_doctype, reference_name, amount=None, notes=None, pos_device_id=None, make_default=0):
    _require_payment_role()
    if not is_doctype_enabled(reference_doctype):
        frappe.throw(f"Payment Orchestrator is disabled for {reference_doctype}")

    settings = get_settings()
    if not is_pinelabs_pos_enabled(settings=settings):
        frappe.throw("Pine Labs POS is disabled in Payment Orchestrator Settings")

    invoice_name = _resolve_demo_invoice(reference_doctype, reference_name)
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
        _set_default_pos_device(pos_device_id)
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

    _ensure_mode_of_payment(getattr(get_settings(), "pos_mode_of_payment", None) or "Pine Labs POS")
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


def _resolve_demo_invoice(reference_doctype, reference_name):
    if reference_doctype == "Sales Invoice":
        invoice = frappe.get_doc("Sales Invoice", reference_name)
        if invoice.docstatus != 1:
            frappe.throw("Demo POS payment needs a submitted Sales Invoice")
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


def _ensure_mode_of_payment(mode):
    if mode and not frappe.db.exists("Mode of Payment", mode):
        frappe.get_doc({"doctype": "Mode of Payment", "mode_of_payment": mode, "enabled": 1}).insert(ignore_permissions=True)


def _set_default_pos_device(pos_device_id):
    frappe.db.set_single_value("Payment Orchestrator Settings", "default_pos_device_id", pos_device_id)
    frappe.db.set_single_value("Payment Orchestrator Settings", "pinelabs_client_id", pos_device_id)
