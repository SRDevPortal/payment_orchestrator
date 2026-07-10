from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from payment_orchestrator.provider.pinelabs.payment_link import PineLabsPaymentLinkAdapter
from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.provider.razorpay.qr_code import RazorpayQRCodeAdapter, resolve_qr_image_url
from payment_orchestrator.api.common.validation import (
    has_payment_action_permission,
    payment_action_role_profiles,
    payment_action_roles,
)
from payment_orchestrator.api.pinelabs import pinelabs_amount, resolve_pos_request_type
from payment_orchestrator.logic import _extract_payment_entity, _resolve_mode_of_payment
from payment_orchestrator.api.whatsapp import ensure_whatsapp_supported_payment_intent
from payment_orchestrator.notifications.whatsapp import (
    build_payment_template_payload,
    build_payment_whatsapp_message,
    find_approved_whatsapp_template,
    is_template_fallback_error,
    normalize_mobile,
    payment_whatsapp_delivery_audit_values,
    payment_instruction,
    payment_template_body_preview,
    payment_template_name_for_intent,
    payment_whatsapp_audit_values,
    payment_whatsapp_transport,
    resolve_approved_payment_template,
    resolve_payment_channel_account,
)
from payment_orchestrator.payment_orchestrator.doctype.payment_orchestrator_settings.payment_orchestrator_settings import (
    PINELABS_BASE_URL,
    PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY,
    PINELABS_ONLINE_BASE_URL,
    RAZORPAY_API_BASE_URL,
    PaymentOrchestratorSettings,
)
from payment_orchestrator.utils import (
    ensure_mode_of_payment,
    get_provider_mode_for_gateway_mode,
    is_gateway_enabled,
    is_gateway_mode_enabled,
    is_pinelabs_payment_link_enabled,
    is_pinelabs_pos_enabled,
    is_razorpay_payment_link_enabled,
)


class ResetInactiveGatewayFieldsTests(TestCase):
    def _settings(self, **overrides):
        class Settings(SimpleNamespace):
            def clear_secret(self, fieldname):
                self.cleared_secrets.append(fieldname)

        defaults = {
            "cleared_secrets": [],
            "enable_razorpay": 1,
            "enable_razorpay_payment_link": 1,
            "enable_razorpay_qr_code": 1,
            "enable_razorpay_pos": 1,
            "enable_razorpay_webhook_processing": 1,
            "razorpay_payment_link_mode": "Live",
            "razorpay_qr_code_mode": "Live",
            "razorpay_pos_mode": "Live",
            "key_id": "legacy_rzp_key",
            "razorpay_test_key_id": "rzp_test_key",
            "razorpay_live_key_id": "rzp_live_key",
            "api_base_url": "https://custom.razorpay.example/v1",
            "enable_pinelabs": 1,
            "enable_pinelabs_payment_link": 1,
            "enable_pinelabs_pos": 1,
            "enable_pinelabs_postback_processing": 1,
            "pinelabs_payment_link_mode": "Live",
            "pinelabs_payment_link_after_payment_display": "Payment Orchestrator Page",
            "pinelabs_online_client_id": "online-client",
            "pinelabs_online_base_url": "https://custom-pinelabs.example",
            "pinelabs_payment_link_callback_url": "https://example.com/success",
            "pinelabs_payment_link_failure_callback_url": "https://example.com/fail",
            "pinelabs_pos_mode": "Live",
            "pinelabs_merchant_id": "merchant",
            "pinelabs_store_id": "store",
            "pinelabs_client_id": "client",
            "pinelabs_user_id": "user",
            "pinelabs_allowed_payment_mode": "1",
            "pinelabs_auto_cancel_duration": 10,
            "pinelabs_base_url": "https://custom-pos.example",
            "default_pos_device_id": "device",
            "pos_timeout_seconds": 45,
            "pos_mode_of_payment": "Custom POS",
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_disabled_razorpay_resets_all_razorpay_fields(self):
        settings = self._settings(enable_razorpay=0)

        PaymentOrchestratorSettings.reset_inactive_razorpay_fields(settings)

        self.assertEqual(settings.enable_razorpay_payment_link, 0)
        self.assertEqual(settings.enable_razorpay_qr_code, 0)
        self.assertEqual(settings.enable_razorpay_pos, 0)
        self.assertEqual(settings.enable_razorpay_webhook_processing, 0)
        self.assertEqual(settings.razorpay_payment_link_mode, "Test")
        self.assertEqual(settings.razorpay_qr_code_mode, "Test")
        self.assertEqual(settings.razorpay_pos_mode, "Test")
        self.assertIsNone(settings.razorpay_test_key_id)
        self.assertIsNone(settings.razorpay_live_key_id)
        self.assertEqual(settings.api_base_url, RAZORPAY_API_BASE_URL)
        self.assertEqual(settings.cleared_secrets, ["razorpay_test_key_secret", "razorpay_live_key_secret", "webhook_secret"])

    def test_pinelabs_resets_only_disabled_mode_fields(self):
        settings = self._settings(enable_pinelabs_payment_link=0, enable_pinelabs_pos=1)

        PaymentOrchestratorSettings.reset_inactive_pinelabs_fields(settings)

        self.assertEqual(settings.pinelabs_payment_link_mode, "Test")
        self.assertEqual(settings.pinelabs_payment_link_after_payment_display, PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY)
        self.assertIsNone(settings.pinelabs_online_client_id)
        self.assertEqual(settings.pinelabs_online_base_url, PINELABS_ONLINE_BASE_URL)
        self.assertIsNone(settings.pinelabs_payment_link_callback_url)
        self.assertIn("pinelabs_online_client_secret", settings.cleared_secrets)

        self.assertEqual(settings.pinelabs_pos_mode, "Live")
        self.assertEqual(settings.pinelabs_merchant_id, "merchant")
        self.assertEqual(settings.pinelabs_base_url, "https://custom-pos.example")
        self.assertNotIn("pinelabs_security_token", settings.cleared_secrets)

    def test_disabled_pinelabs_resets_link_and_pos_fields(self):
        settings = self._settings(enable_pinelabs=0)

        PaymentOrchestratorSettings.reset_inactive_pinelabs_fields(settings)

        self.assertEqual(settings.enable_pinelabs_payment_link, 0)
        self.assertEqual(settings.enable_pinelabs_pos, 0)
        self.assertEqual(settings.enable_pinelabs_postback_processing, 0)
        self.assertEqual(settings.pinelabs_payment_link_mode, "Test")
        self.assertEqual(settings.pinelabs_pos_mode, "Test")
        self.assertIsNone(settings.pinelabs_online_client_id)
        self.assertIsNone(settings.pinelabs_merchant_id)
        self.assertEqual(settings.pinelabs_base_url, PINELABS_BASE_URL)
        self.assertEqual(settings.cleared_secrets, ["pinelabs_online_client_secret", "pinelabs_security_token"])


class PaymentActionAccessTests(TestCase):
    def test_payment_action_roles_fall_back_to_legacy_account_roles(self):
        settings = SimpleNamespace(allowed_payment_action_roles=[], allowed_payment_action_role_profiles=[])

        self.assertEqual(
            payment_action_roles(settings),
            {"Accounts Manager", "Accounts User", "System Manager"},
        )

    def test_payment_action_roles_use_configured_rows(self):
        settings = SimpleNamespace(
            allowed_payment_action_roles=[SimpleNamespace(role="Payment Action User")],
            allowed_payment_action_role_profiles=[],
        )

        self.assertEqual(payment_action_roles(settings), {"Payment Action User"})

    def test_payment_action_role_profiles_use_configured_rows(self):
        settings = SimpleNamespace(
            allowed_payment_action_roles=[],
            allowed_payment_action_role_profiles=[SimpleNamespace(role_profile="Vobiz Agent")],
        )

        self.assertEqual(payment_action_role_profiles(settings), {"Vobiz Agent"})

    def test_has_payment_action_permission_allows_matching_role_profile(self):
        settings = SimpleNamespace(
            allowed_payment_action_roles=[SimpleNamespace(role="Payment Action User")],
            allowed_payment_action_role_profiles=[SimpleNamespace(role_profile="Vobiz Agent")],
        )
        fake_frappe = SimpleNamespace(
            get_roles=lambda user=None: ["Vobiz Agent"],
            db=SimpleNamespace(get_value=lambda *args, **kwargs: "Vobiz Agent"),
        )

        with patch("payment_orchestrator.api.common.validation.frappe", fake_frappe):
            self.assertTrue(has_payment_action_permission(user="agent@example.com", settings=settings))

    def test_has_payment_action_permission_rejects_unconfigured_user(self):
        settings = SimpleNamespace(
            allowed_payment_action_roles=[SimpleNamespace(role="Payment Action User")],
            allowed_payment_action_role_profiles=[SimpleNamespace(role_profile="Billing Agent")],
        )
        fake_frappe = SimpleNamespace(
            get_roles=lambda user=None: ["Vobiz Agent"],
            db=SimpleNamespace(get_value=lambda *args, **kwargs: "Vobiz Agent"),
        )

        with patch("payment_orchestrator.api.common.validation.frappe", fake_frappe):
            self.assertFalse(has_payment_action_permission(user="agent@example.com", settings=settings))


class ModeOfPaymentResolutionTests(TestCase):
    def _settings(self, **overrides):
        defaults = {
            "default_mode_of_payment": "Razorpay",
            "pos_mode_of_payment": "Pine Labs POS",
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def _intent(self, gateway, payment_mode):
        return SimpleNamespace(gateway=gateway, payment_mode=payment_mode, request_channel=payment_mode)

    def _resolve(self, intent, settings):
        fake_frappe = SimpleNamespace(
            db=SimpleNamespace(exists=lambda *args, **kwargs: True),
            get_doc=lambda *args, **kwargs: None,
        )
        with patch("payment_orchestrator.logic.frappe", fake_frappe), patch(
            "payment_orchestrator.logic.ensure_mode_of_payment",
            side_effect=lambda mode: mode,
        ):
            return _resolve_mode_of_payment(intent, settings)

    def test_razorpay_link_and_qr_use_razorpay_mode_of_payment(self):
        settings = self._settings()

        self.assertEqual(self._resolve(self._intent("Razorpay", "Payment Link"), settings), "Razorpay")
        self.assertEqual(self._resolve(self._intent("Razorpay", "QR Code"), settings), "Razorpay")

    def test_razorpay_pos_uses_razorpay_pos_mode_of_payment(self):
        self.assertEqual(
            self._resolve(self._intent("Razorpay", "POS"), self._settings()),
            "Razorpay POS",
        )

    def test_pinelabs_link_and_qr_use_pinelabs_mode_of_payment(self):
        settings = self._settings()

        self.assertEqual(self._resolve(self._intent("Pine Labs", "Payment Link"), settings), "Pine Labs")
        self.assertEqual(self._resolve(self._intent("Pine Labs", "QR Code"), settings), "Pine Labs")

    def test_pinelabs_pos_uses_pinelabs_pos_mode_of_payment(self):
        self.assertEqual(
            self._resolve(self._intent("Pine Labs", "POS"), self._settings()),
            "Pine Labs POS",
        )


class EnsureModeOfPaymentTests(TestCase):
    def test_empty_mode_is_ignored(self):
        fake_frappe = SimpleNamespace(
            db=SimpleNamespace(exists=lambda *args, **kwargs: False),
            get_doc=lambda *args, **kwargs: None,
        )

        with patch("payment_orchestrator.utils.frappe", fake_frappe):
            self.assertIsNone(ensure_mode_of_payment(""))

    def test_existing_mode_is_returned_without_insert(self):
        fake_frappe = SimpleNamespace(
            db=SimpleNamespace(exists=lambda *args, **kwargs: True),
            get_doc=lambda *args, **kwargs: self.fail("get_doc should not be called"),
        )

        with patch("payment_orchestrator.utils.frappe", fake_frappe):
            self.assertEqual(ensure_mode_of_payment("Razorpay"), "Razorpay")

    def test_missing_mode_is_created_enabled(self):
        inserted = []

        class FakeDoc(dict):
            def insert(self, ignore_permissions=False):
                inserted.append((dict(self), ignore_permissions))

        fake_frappe = SimpleNamespace(
            db=SimpleNamespace(exists=lambda *args, **kwargs: False),
            get_doc=lambda values: FakeDoc(values),
        )

        with patch("payment_orchestrator.utils.frappe", fake_frappe):
            self.assertEqual(ensure_mode_of_payment("Pine Labs POS"), "Pine Labs POS")

        self.assertEqual(inserted, [({
            "doctype": "Mode of Payment",
            "mode_of_payment": "Pine Labs POS",
            "enabled": 1,
        }, True)])


class WhatsAppPaymentNotificationTests(TestCase):
    def test_normalize_mobile_defaults_indian_ten_digit_numbers(self):
        self.assertEqual(normalize_mobile("98765 43210"), "919876543210")
        self.assertEqual(normalize_mobile("+91-98765-43210"), "919876543210")

    def test_payment_link_message_contains_payment_url_and_reference(self):
        intent = SimpleNamespace(
            amount_requested=10,
            currency="INR",
            payment_mode="Payment Link",
            payment_link_url="https://rzp.io/rzp/test",
            qr_code_url=None,
            reference_doctype="Patient Encounter",
            reference_name="HLC-ENC-1",
            party_name="Test Patient",
            company="Test Clinic",
        )

        message = build_payment_whatsapp_message(intent, {"display_name": "Test Patient"})

        self.assertIn("₹ 10.00", message)
        self.assertIn("https://rzp.io/rzp/test", message)
        self.assertIn("Reference: Patient Encounter HLC-ENC-1", message)

    def test_pos_instruction_does_not_require_link(self):
        intent = SimpleNamespace(payment_mode="POS", payment_link_url=None, qr_code_url=None)

        self.assertIn("POS terminal", payment_instruction(intent))

    def test_qr_uses_image_transport_for_interakt(self):
        intent = SimpleNamespace(name="PI-1", payment_mode="QR Code", qr_code_url="https://rzp.io/rzp/test")
        fake_frappe = SimpleNamespace(db=SimpleNamespace(get_value=lambda *args, **kwargs: "Interakt"))

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe), patch(
            "payment_orchestrator.notifications.whatsapp.interakt_qr_image_url",
            return_value="https://interakt.example/payment-qr-PI-1.png",
        ):
            self.assertEqual(
                payment_whatsapp_transport(intent, "WA Account"),
                ("Image", "https://interakt.example/payment-qr-PI-1.png"),
            )

    def test_whatsapp_guard_allows_payment_link_with_url(self):
        intent = SimpleNamespace(payment_mode="Payment Link", payment_link_url="https://rzp.io/rzp/test", qr_code_url=None)

        ensure_whatsapp_supported_payment_intent(intent)

    def test_whatsapp_guard_rejects_payment_link_without_url(self):
        intent = SimpleNamespace(payment_mode="Payment Link", payment_link_url=None, qr_code_url=None)

        with self._whatsapp_throw_patch(), self.assertRaisesRegex(Exception, "payment link URL is missing"):
            ensure_whatsapp_supported_payment_intent(intent)

    def test_whatsapp_guard_allows_qr_code_with_url(self):
        intent = SimpleNamespace(payment_mode="QR Code", payment_link_url=None, qr_code_url="https://rzp.io/rzp/test")

        ensure_whatsapp_supported_payment_intent(intent)

    def test_whatsapp_guard_rejects_qr_code_without_url(self):
        intent = SimpleNamespace(payment_mode="QR Code", payment_link_url=None, qr_code_url=None)

        with self._whatsapp_throw_patch(), self.assertRaisesRegex(Exception, "QR code URL is missing"):
            ensure_whatsapp_supported_payment_intent(intent)

    def test_whatsapp_guard_rejects_pos_and_unknown_modes(self):
        for payment_mode in ("POS", "Checkout", "Manual Share", ""):
            with self.subTest(payment_mode=payment_mode):
                intent = SimpleNamespace(payment_mode=payment_mode, payment_link_url="https://example.com", qr_code_url="https://example.com")
                with self._whatsapp_throw_patch(), self.assertRaisesRegex(Exception, "Payment Link and QR Code"):
                    ensure_whatsapp_supported_payment_intent(intent)

    def test_whatsapp_audit_values_are_plain_strings(self):
        with patch("payment_orchestrator.notifications.whatsapp.now_datetime", return_value=datetime(2026, 7, 7, 10, 0, 0)):
            values = payment_whatsapp_audit_values(
                recipient={"mobile_no": "919876543210"},
                channel_account="SRIAAS ODIA",
                message="787",
                content_type="Image",
                status="Sent",
                error=None,
            )

        self.assertEqual(values["last_whatsapp_recipient"], "919876543210")
        self.assertEqual(values["last_whatsapp_channel_account"], "SRIAAS ODIA")
        self.assertEqual(values["last_whatsapp_message"], "787")
        self.assertEqual(values["last_whatsapp_content_type"], "Image")
        self.assertEqual(values["whatsapp_send_status"], "Sent")
        self.assertIsNone(values["last_whatsapp_error"])
        self.assertIn("last_whatsapp_sent_on", values)

    def test_successful_template_fallback_does_not_store_last_error(self):
        with patch("payment_orchestrator.notifications.whatsapp.now_datetime", return_value=datetime(2026, 7, 7, 10, 0, 0)):
            values = payment_whatsapp_audit_values(
                recipient={"mobile_no": "919876543210"},
                channel_account="Siya Ayurveda",
                message="391",
                content_type="Template",
                status="Sent",
                error=None,
            )

        self.assertEqual(values["last_whatsapp_content_type"], "Template")
        self.assertEqual(values["whatsapp_send_status"], "Sent")
        self.assertIsNone(values["last_whatsapp_error"])

    def test_delivery_audit_values_clear_error_for_success_status(self):
        values = payment_whatsapp_delivery_audit_values(
            SimpleNamespace(delivery_status="Read", raw_payload='{"error":"old provider error"}')
        )

        self.assertEqual(values["whatsapp_send_status"], "Read")
        self.assertIsNone(values["last_whatsapp_error"])

    def test_delivery_audit_values_store_failed_error(self):
        values = payment_whatsapp_delivery_audit_values(
            SimpleNamespace(
                delivery_status="Failed",
                raw_payload='{"error":{"message":"Recipient phone number is invalid"}}',
                raw_transport_payload=None,
            )
        )

        self.assertEqual(values["whatsapp_send_status"], "Failed")
        self.assertEqual(values["last_whatsapp_error"], "Recipient phone number is invalid")

    def test_template_fallback_error_detection(self):
        self.assertTrue(is_template_fallback_error("WhatsApp only allows free-text replies within 24 hours"))
        self.assertTrue(is_template_fallback_error("outside customer service window"))
        self.assertTrue(is_template_fallback_error("Use the Template button"))
        self.assertFalse(is_template_fallback_error("Interakt API Key is not configured"))
        self.assertFalse(is_template_fallback_error("mediaUrl should contain valid public URLs"))

    def test_payment_template_payload_uses_four_approved_variables(self):
        intent = SimpleNamespace(
            amount_requested=10,
            currency="INR",
            payment_link_url="https://rzp.io/rzp/test123",
            qr_code_url=None,
            reference_doctype="Patient Encounter",
            reference_name="HLC-ENC-2026-00106",
            party_name="Jitendra Kumar",
            company="SR Institute of Advanced Ayurvedic Sciences Private Limited",
        )
        settings = SimpleNamespace(
            enable_whatsapp_template_fallback=1,
            whatsapp_payment_request_template="payment_request",
            whatsapp_template_language="en",
        )
        fake_frappe = SimpleNamespace(
            get_single=lambda doctype: settings,
            defaults=SimpleNamespace(get_user_default=lambda key: None),
            throw=lambda message: (_ for _ in ()).throw(Exception(str(message))),
        )

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe):
            payload = build_payment_template_payload(intent, {"display_name": "Jitendra Kumar"})

        self.assertEqual(payload["template_name"], "payment_request")
        self.assertEqual(payload["language_code"], "en")
        self.assertEqual(
            payload["body_values"],
            [
                "Jitendra Kumar",
                "SR Institute of Advanced Ayurvedic Sciences Private Limited",
                "Amount: ₹ 10.00 | Reference: Patient Encounter HLC-ENC-2026-00106",
                "https://rzp.io/rzp/test123",
            ],
        )
        self.assertIn("Payment details:", payload["body_preview"])

    def test_payment_template_name_uses_qr_template_when_present(self):
        settings = SimpleNamespace(
            whatsapp_payment_request_template="payment_request",
            whatsapp_qr_code_template="payment_qr_request",
        )

        self.assertEqual(
            payment_template_name_for_intent(settings, SimpleNamespace(payment_mode="Payment Link")),
            "payment_request",
        )
        self.assertEqual(
            payment_template_name_for_intent(settings, SimpleNamespace(payment_mode="QR Code")),
            "payment_qr_request",
        )

    def test_payment_template_name_falls_back_to_link_template_for_qr(self):
        settings = SimpleNamespace(
            whatsapp_payment_request_template="payment_request",
            whatsapp_qr_code_template="",
        )

        self.assertEqual(
            payment_template_name_for_intent(settings, SimpleNamespace(payment_mode="QR Code")),
            "payment_request",
        )

    def test_find_approved_whatsapp_template_matches_exact_name(self):
        templates = [
            {"name": "payment_request_32", "display_name": "payment_request", "language_code": "en", "languages": ["en"]},
        ]

        match = find_approved_whatsapp_template(templates, "payment_request_32", "en")

        self.assertEqual(match["name"], "payment_request_32")

    def test_resolve_approved_payment_template_accepts_display_name_alias(self):
        template = {"template_name": "payment_request", "language_code": "en"}
        approved = [
            {"name": "payment_request_32", "display_name": "payment_request", "language_code": "en", "languages": ["en"]},
        ]

        with patch("payment_orchestrator.notifications.whatsapp.fetch_approved_whatsapp_templates", return_value=approved):
            resolved = resolve_approved_payment_template("SRIAAS ODIA", template)

        self.assertEqual(resolved["template_name"], "payment_request_32")
        self.assertEqual(resolved["configured_template_name"], "payment_request")

    def test_payment_template_body_preview_matches_approved_shape(self):
        preview = payment_template_body_preview([
            "Jitendra Kumar",
            "SR Institute",
            "Amount: ₹ 10.00 | Reference: Patient Encounter HLC-ENC-1",
            "https://rzp.io/rzp/test123",
        ])

        self.assertIn("Dear Jitendra Kumar,", preview)
        self.assertIn("This is a payment request from SR Institute.", preview)
        self.assertIn("Please use the secure payment link below", preview)
        self.assertIn("Thank you.", preview)

    def test_payment_template_body_preview_for_qr_mentions_image(self):
        preview = payment_template_body_preview(
            [
                "Jitendra Kumar",
                "SR Institute",
                "Amount: â‚¹ 10.00 | Reference: Patient Encounter HLC-ENC-1",
                "https://api.razorpay.com/v1/l/qrcode/qr_123",
            ],
            is_qr=True,
        )

        self.assertIn("Please scan the QR image above", preview)
        self.assertIn("https://api.razorpay.com/v1/l/qrcode/qr_123", preview)

    def _whatsapp_throw_patch(self):
        return patch(
            "payment_orchestrator.api.whatsapp.frappe.throw",
            side_effect=lambda message: (_ for _ in ()).throw(Exception(str(message))),
        )

    def test_existing_active_conversation_channel_wins(self):
        fake_frappe = self._fake_channel_frappe(
            conversations=[SimpleNamespace(channel_account="Existing Interakt")],
            accounts={"Existing Interakt": self._account("Interakt", 1, "Active")},
            default_channel="Default Interakt",
        )

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe):
            self.assertEqual(
                resolve_payment_channel_account({"mobile_no": "919876543210"}, contact="CONTACT-1"),
                "Existing Interakt",
            )

    def test_default_channel_is_used_when_no_existing_conversation(self):
        fake_frappe = self._fake_channel_frappe(
            conversations=[],
            accounts={"Default Interakt": self._account("Interakt", 1, "Active")},
            default_channel="Default Interakt",
        )

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe):
            self.assertEqual(
                resolve_payment_channel_account({"mobile_no": "919876543210"}, contact="CONTACT-1"),
                "Default Interakt",
            )

    def test_invalid_existing_conversation_channel_is_skipped(self):
        fake_frappe = self._fake_channel_frappe(
            conversations=[
                SimpleNamespace(channel_account="Inactive Interakt"),
                SimpleNamespace(channel_account="Personal WA"),
                SimpleNamespace(channel_account="Existing Interakt"),
            ],
            accounts={
                "Inactive Interakt": self._account("Interakt", 0, "Active"),
                "Personal WA": self._account("Personal", 1, "Active"),
                "Existing Interakt": self._account("Interakt", 1, "Active"),
            },
            default_channel="Default Interakt",
        )

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe):
            self.assertEqual(
                resolve_payment_channel_account({"mobile_no": "919876543210"}, contact="CONTACT-1"),
                "Existing Interakt",
            )

    def test_missing_conversation_and_default_channel_raises_clear_error(self):
        fake_frappe = self._fake_channel_frappe(conversations=[], accounts={}, default_channel=None)

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe):
            with self.assertRaisesRegex(Exception, "No active WhatsApp conversation found"):
                resolve_payment_channel_account({"mobile_no": "919876543210"}, contact="CONTACT-1")

    def test_invalid_default_channel_raises_clear_error(self):
        fake_frappe = self._fake_channel_frappe(
            conversations=[],
            accounts={"Default Interakt": self._account("Interakt", 0, "Active")},
            default_channel="Default Interakt",
        )

        with patch("payment_orchestrator.notifications.whatsapp.frappe", fake_frappe):
            with self.assertRaisesRegex(Exception, "inactive, disconnected, or not an Interakt"):
                resolve_payment_channel_account({"mobile_no": "919876543210"}, contact="CONTACT-1")

    def _fake_channel_frappe(self, conversations, accounts, default_channel):
        def get_value(doctype, filters=None, fieldname=None, **kwargs):
            if doctype == "Chat Channel Account":
                return accounts.get(filters)
            if doctype == "Chat Contact":
                return "CONTACT-1"
            return None

        return SimpleNamespace(
            db=SimpleNamespace(get_value=get_value),
            get_meta=lambda doctype: SimpleNamespace(has_field=lambda fieldname: fieldname == "status"),
            get_all=lambda *args, **kwargs: conversations,
            get_single=lambda doctype: SimpleNamespace(default_whatsapp_channel_account=default_channel),
            throw=lambda message: (_ for _ in ()).throw(Exception(str(message))),
            _=lambda message: message,
        )

    def _account(self, channel_type, is_active, connector_status):
        return SimpleNamespace(
            channel_type=channel_type,
            is_active=is_active,
            connector_status=connector_status,
        )


class GatewayModeFlagTests(TestCase):
    def _settings(self, **overrides):
        defaults = {
            "provider_enabled": 1,
            "enable_payment_links": 1,
            "enable_pos_payments": 1,
            "enable_razorpay": 1,
            "enable_razorpay_payment_link": 1,
            "enable_razorpay_qr_code": 0,
            "enable_razorpay_pos": 0,
            "enable_pinelabs": 1,
            "enable_pinelabs_payment_link": 0,
            "enable_pinelabs_pos": 1,
            "provider_mode": "Test",
            "razorpay_payment_link_mode": "Live",
            "razorpay_qr_code_mode": "Test",
            "razorpay_pos_mode": "Test",
            "pinelabs_payment_link_mode": "Live",
            "pinelabs_pos_mode": "Test",
        }
        defaults.update(overrides)
        return SimpleNamespace(**defaults)

    def test_gateway_enabled_requires_provider_and_gateway_flag(self):
        self.assertTrue(is_gateway_enabled("Razorpay", settings=self._settings()))
        self.assertFalse(is_gateway_enabled("Razorpay", settings=self._settings(provider_enabled=0)))
        self.assertFalse(is_gateway_enabled("Pine Labs", settings=self._settings(enable_pinelabs=0)))

    def test_default_gateway_mode_matrix(self):
        settings = self._settings()

        self.assertTrue(is_razorpay_payment_link_enabled(settings=settings))
        self.assertFalse(is_gateway_mode_enabled("Razorpay", "QR Code", settings=settings))
        self.assertFalse(is_gateway_mode_enabled("Razorpay", "POS", settings=settings))
        self.assertFalse(is_pinelabs_payment_link_enabled(settings=settings))
        self.assertTrue(is_pinelabs_pos_enabled(settings=settings))

    def test_global_mode_switches_override_gateway_mode_flags(self):
        self.assertFalse(
            is_razorpay_payment_link_enabled(settings=self._settings(enable_payment_links=0))
        )
        self.assertFalse(
            is_pinelabs_pos_enabled(settings=self._settings(enable_pos_payments=0))
        )

    def test_provider_mode_is_resolved_per_gateway_payment_mode(self):
        settings = self._settings()

        self.assertEqual(get_provider_mode_for_gateway_mode("Razorpay", "Payment Link", settings), "Live")
        self.assertEqual(get_provider_mode_for_gateway_mode("Razorpay", "QR Code", settings), "Test")
        self.assertEqual(get_provider_mode_for_gateway_mode("Razorpay", "POS", settings), "Test")
        self.assertEqual(get_provider_mode_for_gateway_mode("Pine Labs", "Payment Link", settings), "Live")
        self.assertEqual(get_provider_mode_for_gateway_mode("Pine Labs", "POS", settings), "Test")


class RazorpayClientCredentialModeTests(TestCase):
    def _settings(self):
        class Settings(SimpleNamespace):
            def get_password(self, fieldname, raise_exception=False):
                return {
                    "razorpay_test_key_secret": "test_secret",
                    "razorpay_live_key_secret": "live_secret",
                    "key_secret": "legacy_secret",
                }.get(fieldname)

        return Settings(
            api_base_url="https://api.razorpay.com/v1",
            razorpay_test_key_id="rzp_test_key",
            razorpay_live_key_id="rzp_live_key",
            key_id="legacy_key",
        )

    def test_client_uses_test_credentials_for_test_mode(self):
        client = RazorpayClient(settings=self._settings(), mode="Test")

        self.assertEqual(client._key_id(), "rzp_test_key")
        self.assertEqual(client._key_secret(), "test_secret")

    def test_client_uses_live_credentials_for_live_mode(self):
        client = RazorpayClient(settings=self._settings(), mode="Live")

        self.assertEqual(client._key_id(), "rzp_live_key")
        self.assertEqual(client._key_secret(), "live_secret")


class PineLabsPaymentLinkAdapterTests(TestCase):
    def _settings(self, secret=None, **overrides):
        class Settings(SimpleNamespace):
            def get_password(self, fieldname, raise_exception=False):
                return secret

        defaults = {
            "pinelabs_online_client_id": "client-id",
            "pinelabs_payment_link_allowed_methods": "CARD,UPI",
            "pinelabs_payment_link_after_payment_display": PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY,
        }
        defaults.update(overrides)
        return Settings(**defaults)

    def test_adapter_requires_online_credentials(self):
        adapter = PineLabsPaymentLinkAdapter(settings=self._settings(secret=None))

        with patch("frappe.throw", side_effect=Exception) as throw:
            with self.assertRaises(Exception):
                adapter.ensure_available()

        throw.assert_called_once()
        self.assertIn("Client Secret", throw.call_args.args[0])

    def test_build_payload_matches_pinelabs_payment_link_shape(self):
        adapter = PineLabsPaymentLinkAdapter(settings=self._settings(secret="secret"))
        intent = SimpleNamespace(
            name="PI-0001",
            amount_requested=125.5,
            currency="INR",
            reference_doctype="Sales Invoice",
            reference_name="SINV-0001",
            request_type="Against Invoice",
            expires_on=datetime(2026, 1, 1, 12, 30),
            party_name="Test Customer",
            party_email="test@example.com",
            party_mobile="9876543210",
            party="CUST-0001",
        )

        payload = adapter.build_payload(intent, {"allow_partial": True})

        self.assertEqual(payload["amount"], {"value": 12550, "currency": "INR"})
        self.assertEqual(payload["merchant_payment_link_reference"], "PI-0001")
        self.assertEqual(payload["allowed_payment_methods"], ["CARD", "UPI"])
        self.assertFalse(payload["part_payment"])
        self.assertEqual(payload["customer"]["mobile_number"], "9876543210")
        self.assertNotIn("callback_url", payload)
        self.assertNotIn("failure_callback_url", payload)

    def test_build_payload_can_send_orchestrator_callback_urls(self):
        adapter = PineLabsPaymentLinkAdapter(settings=self._settings(
            secret="secret",
            pinelabs_payment_link_after_payment_display="Payment Orchestrator Page",
        ))
        intent = SimpleNamespace(
            name="PI-0001",
            amount_requested=1,
            currency="INR",
            reference_doctype="Sales Invoice",
            reference_name="SINV-0001",
            request_type="Against Invoice",
            expires_on=None,
            party_name="Test Customer",
            party_email="test@example.com",
            party_mobile="9876543210",
            party="CUST-0001",
        )

        with patch("payment_orchestrator.provider.pinelabs.payment_link.get_public_webhook_url", return_value="https://site.example/api/method/payment_orchestrator.api.webhooks.pinelabs"):
            payload = adapter.build_payload(intent, {"allow_partial": False})

        self.assertEqual(payload["callback_url"], "https://site.example/api/method/payment_orchestrator.api.webhooks.pinelabs")
        self.assertEqual(payload["failure_callback_url"], "https://site.example/api/method/payment_orchestrator.api.webhooks.pinelabs")


class RazorpayWebhookPayloadTests(TestCase):
    def test_payment_link_paid_without_nested_payment_resolves_link_context(self):
        payload = {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_123",
                        "amount": 100,
                        "amount_paid": 100,
                        "status": "paid",
                        "notes": {"payment_intent": "PI-0001"},
                    }
                }
            },
        }

        entity = _extract_payment_entity(payload)

        self.assertEqual(entity["id"], "plink_123")
        self.assertEqual(entity["payment_link_id"], "plink_123")
        self.assertEqual(entity["amount"], 100)
        self.assertEqual(entity["notes"]["payment_intent"], "PI-0001")

    def test_payment_link_paid_nested_payment_inherits_link_notes(self):
        payload = {
            "event": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_123",
                        "amount": 100,
                        "amount_paid": 100,
                        "status": "paid",
                        "notes": {"payment_intent": "PI-0001"},
                        "payments": [{"id": "pay_123", "status": "captured"}],
                    }
                }
            },
        }

        entity = _extract_payment_entity(payload)

        self.assertEqual(entity["id"], "pay_123")
        self.assertEqual(entity["payment_link_id"], "plink_123")
        self.assertEqual(entity["amount"], 100)
        self.assertEqual(entity["notes"]["payment_intent"], "PI-0001")

    def test_qr_code_credited_payment_inherits_qr_context(self):
        payload = {
            "event": "qr_code.credited",
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_123",
                        "amount": 200,
                        "status": "captured",
                        "notes": {},
                    }
                },
                "qr_code": {
                    "entity": {
                        "id": "qr_123",
                        "notes": {"payment_intent": "PI-QR-0001"},
                    }
                },
            },
        }

        entity = _extract_payment_entity(payload)

        self.assertEqual(entity["id"], "pay_123")
        self.assertEqual(entity["qr_code_id"], "qr_123")
        self.assertEqual(entity["amount"], 200)
        self.assertEqual(entity["notes"]["payment_intent"], "PI-QR-0001")


class PineLabsAmountTests(TestCase):
    def test_transaction_data_amount_is_minor_units(self):
        response = {"TransactionData": [{"Tag": "Amount", "Value": "500"}]}

        self.assertEqual(pinelabs_amount(response), 5)

    def test_top_level_amount_is_minor_units(self):
        response = {"Amount": "12550"}

        self.assertEqual(pinelabs_amount(response), 125.5)


class PineLabsPOSRequestTypeTests(TestCase):
    def test_sales_invoice_defaults_to_against_invoice(self):
        self.assertEqual(resolve_pos_request_type("Sales Invoice"), "Against Invoice")

    def test_patient_encounter_defaults_to_advance(self):
        self.assertEqual(resolve_pos_request_type("Patient Encounter"), "Advance")

    def test_patient_encounter_allows_against_invoice(self):
        self.assertEqual(resolve_pos_request_type("Patient Encounter", "Against Invoice"), "Against Invoice")


class RazorpayQRCodeAdapterTests(TestCase):
    def test_create_qr_code_payload_is_single_use_fixed_amount(self):
        settings = SimpleNamespace(api_base_url="https://api.razorpay.com/v1")
        adapter = RazorpayQRCodeAdapter(settings=settings)
        intent = SimpleNamespace(
            name="PI-QR-0001",
            amount_requested=2,
            currency="INR",
            reference_doctype="Sales Invoice",
            reference_name="SINV-0001",
            request_type="Against Invoice",
            expires_on=datetime(2026, 1, 1, 12, 30),
            db_set=lambda *args, **kwargs: None,
            reload=lambda: None,
        )

        with patch.object(adapter.client, "create_qr_code", return_value={
            "id": "qr_123",
            "image_url": "https://rzp.io/rzp/qr123",
            "status": "active",
            "close_by": 1767270600,
        }) as create_qr, patch(
            "payment_orchestrator.provider.razorpay.qr_code.resolve_qr_image_url",
            return_value="https://api.razorpay.com/v1/l/qrcode/qr_123",
        ):
            adapter.create(intent, {"party": "CUST-0001"})

        payload = create_qr.call_args.args[0]
        self.assertEqual(payload["type"], "upi_qr")
        self.assertEqual(payload["usage"], "single_use")
        self.assertTrue(payload["fixed_amount"])
        self.assertEqual(payload["payment_amount"], 200)
        self.assertEqual(payload["notes"]["payment_intent"], "PI-QR-0001")

    def test_resolve_qr_image_url_uses_final_image_redirect_url(self):
        response = SimpleNamespace(
            url="https://api.razorpay.com/v1/l/qrcode/qr_123",
            headers={"Content-Type": "image/png"},
            raise_for_status=lambda: None,
            close=lambda: None,
        )

        with patch("payment_orchestrator.provider.razorpay.qr_code.requests.get", return_value=response):
            self.assertEqual(
                resolve_qr_image_url("https://rzp.io/rzp/qr123"),
                "https://api.razorpay.com/v1/l/qrcode/qr_123",
            )

    def test_resolve_qr_image_url_keeps_original_when_response_is_not_image(self):
        response = SimpleNamespace(
            url="https://rzp.io/rzp/qr123",
            headers={"Content-Type": "text/html"},
            raise_for_status=lambda: None,
            close=lambda: None,
        )

        with patch("payment_orchestrator.provider.razorpay.qr_code.requests.get", return_value=response):
            self.assertEqual(resolve_qr_image_url("https://rzp.io/rzp/qr123"), "https://rzp.io/rzp/qr123")
