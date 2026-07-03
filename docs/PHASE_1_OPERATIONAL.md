# Payment Orchestrator - Phase 1 Operational Build

## Delivered in this pass
- Real Razorpay client wiring for:
  - credential validation
  - payment link creation
  - payment fetch
  - payment link fetch
  - refund creation scaffold
- Payment Intent creation API that generates Razorpay payment links
- Pine Labs POS request flow behind a gateway/mode feature flag
- Pine Labs Payment Link mode implemented behind a disabled-by-default feature flag
- Request Payment action button scaffold on CRM Lead, Patient Encounter, Sales Order, Sales Invoice
- Webhook endpoint with Razorpay signature verification
- Payment Provider Event log for payload retention and idempotent processing foundation
- Payment Entry creation flow on successful payment webhook
- Invoice-linked payments auto-create Payment Allocation rows when request type is `Against Invoice`
- Settings page includes gateway/mode toggles and webhook URL visibility

## Operational limitations still remaining
- Pine Labs Payment Link needs live Pine Labs Online credentials and UAT validation before production use
- lead conversion carry-forward logic is not finished
- no settlement sync yet
- no refund workflow UI yet
- customer/party resolution is best-effort and may need SRIAAS-specific hardening after first live pass

## Primary methods
- `payment_orchestrator.api.razorpay.create_payment_link`
- `payment_orchestrator.api.pinelabs.create_payment_link`
- `payment_orchestrator.api.pinelabs.request_pos_payment`
- `payment_orchestrator.api.settings.test_provider_connection`
- `payment_orchestrator.api.webhooks.razorpay`
- `payment_orchestrator.api.webhooks.pinelabs`

## Expected setup sequence
1. Install app on bench/site.
2. Open `Payment Orchestrator Settings`.
3. Set Test/Live mode.
4. Enter Razorpay key id, secret, webhook secret.
5. Configure default company and receiving accounts.
6. Enable only the required gateway/mode combinations.
7. Enable target doctypes.
8. Set Razorpay webhook URL to the endpoint shown by the settings action.
9. Test from a CRM Lead or Invoice and confirm Payment Intent + webhook + Payment Entry lifecycle.
