# Razorpay Integration - Phase 1 Operational Build

## Delivered in this pass
- Real Razorpay Integration client wiring for:
  - credential validation
  - payment link creation
  - payment fetch
  - payment link fetch
  - refund creation scaffold
- Payment Intent creation API that generates Razorpay Integration payment links
- Request Payment action button scaffold on Lead, Patient Encounter, Sales Order, Sales Invoice
- Webhook endpoint with Razorpay Integration signature verification
- Payment Provider Event log for payload retention and idempotent processing foundation
- Payment Entry creation flow on successful payment webhook
- Invoice-linked payments auto-create Payment Allocation rows when request type is `Against Invoice`
- Settings page includes `Test Razorpay Integration Connection` action and webhook URL visibility

## Operational limitations still remaining
- no install/migration runner yet
- no doctypes summary widgets yet
- encounter and sales-order advance auto-allocation to future invoices is not finished
- lead conversion carry-forward logic is not finished
- no settlement sync yet
- no refund workflow UI yet
- customer/party resolution is best-effort and may need SRIAAS-specific hardening after first live pass

## Primary methods
- `razorpay_integration.api.intents.create_payment_intent`
- `razorpay_integration.api.settings.test_provider_connection`
- `razorpay_integration.api.webhooks.razorpay`

## Expected setup sequence
1. Install app on bench/site.
2. Open `Razorpay Integration Settings`.
3. Set Test/Live mode.
4. Enter Razorpay Integration key id, secret, webhook secret.
5. Configure default company and receiving accounts.
6. Keep payment links enabled.
7. Enable target doctypes.
8. Set Razorpay Integration webhook URL to the endpoint shown by the settings action.
9. Test from a Lead or Invoice and confirm Payment Intent + webhook + Payment Entry lifecycle.
