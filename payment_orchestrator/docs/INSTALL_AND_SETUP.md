# Payment Orchestrator - Install and Setup

## What this app is
A plug-and-play ERPNext/Frappe app for payment collection orchestration across Razorpay and Pine Labs modes.

## Supported entry points
- CRM Lead
- Patient Encounter
- Sales Order
- Sales Invoice

## Core features
- Razorpay payment link generation from ERP doctypes
- Pine Labs POS collection flow
- Pine Labs Online payment-link generation behind a disabled-by-default mode flag
- unified Payment Intent ledger
- webhook-driven payment capture
- Payment Entry creation scaffold
- invoice allocation and advance handling foundation
- doctype-level payment summary
- central settings control plane
- setup status and smoke-check APIs
- refund initiation API
- duplicate webhook protection

## Install

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app /path/to/payment_orchestrator
bench --site yoursite install-app payment_orchestrator
bench --site yoursite migrate
bench --site yoursite clear-cache
bench restart
```

## After install
1. Open `Payment Orchestrator Settings`
2. Set:
   - Provider enabled
   - Test or Live mode
   - Razorpay API Key ID
   - Razorpay API Secret
   - Razorpay Webhook Secret
   - Pine Labs POS credentials, if POS is required
   - Default company
   - Default advance / receivable accounts
   - Default mode of payment
3. Turn on doctypes you want:
   - CRM Lead
   - Patient Encounter
   - Sales Order
   - Sales Invoice
4. Enable only the gateway/mode combinations needed:
   - Razorpay Payment Link
   - Pine Labs POS
   - Pine Labs Payment Link remains disabled until Online credentials are configured and the mode is intentionally enabled
4. Run provider connection test
5. Verify setup via:
   - `/api/method/payment_orchestrator.api.setup.get_setup_status`
   - `/api/method/payment_orchestrator.api.setup.smoke_check`
6. Copy webhook URL and register it in the provider dashboard
7. Create a payment request from any enabled doctype

## Webhooks
Point Razorpay webhook to:

```text
/api/method/payment_orchestrator.api.webhooks.razorpay
```

Point Pine Labs postback to:

```text
/api/method/payment_orchestrator.api.webhooks.pinelabs
```

## Recommended first test order
1. Sales Invoice payment request
2. Patient Encounter advance request
3. Sales Order advance request
4. CRM Lead advance request

## What to verify
- Payment Intent created
- payment link opens correctly
- webhook fires
- Payment Provider Event created
- Payment Entry created or linked
- invoice allocation created where applicable
- doctype summary fields update

## Practical note
`Patient Encounter` support assumes the Healthcare domain exists on the target site. If it does not, test CRM Lead / Sales Order / Sales Invoice first.
