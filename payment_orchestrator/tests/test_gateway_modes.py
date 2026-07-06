from datetime import datetime
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from payment_orchestrator.provider.pinelabs.payment_link import PineLabsPaymentLinkAdapter
from payment_orchestrator.provider.razorpay.client import RazorpayClient
from payment_orchestrator.provider.razorpay.qr_code import RazorpayQRCodeAdapter
from payment_orchestrator.api.pinelabs import pinelabs_amount
from payment_orchestrator.logic import _extract_payment_entity
from payment_orchestrator.payment_orchestrator.doctype.payment_orchestrator_settings.payment_orchestrator_settings import (
    PINELABS_BASE_URL,
    PINELABS_PAYMENT_LINK_DEFAULT_DISPLAY,
    PINELABS_ONLINE_BASE_URL,
    RAZORPAY_API_BASE_URL,
    PaymentOrchestratorSettings,
)
from payment_orchestrator.utils import (
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
        self.assertTrue(payload["part_payment"])
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
        }) as create_qr:
            adapter.create(intent, {"party": "CUST-0001"})

        payload = create_qr.call_args.args[0]
        self.assertEqual(payload["type"], "upi_qr")
        self.assertEqual(payload["usage"], "single_use")
        self.assertTrue(payload["fixed_amount"])
        self.assertEqual(payload["payment_amount"], 200)
        self.assertEqual(payload["notes"]["payment_intent"], "PI-QR-0001")
