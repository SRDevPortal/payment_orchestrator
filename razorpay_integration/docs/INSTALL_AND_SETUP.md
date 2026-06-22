# Razorpay Integration - Install and Setup

## What this app is
A plug-and-play ERPNext/Frappe app for payment collection orchestration using Razorpay Integration as the first provider.

## Supported entry points
- Lead
- Patient Encounter
- Sales Order
- Sales Invoice

## Core features
- payment link generation from ERP doctypes
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
bench get-app /Users/admin/.openclaw/workspace/razorpay
bench --site yoursite install-app razorpay_integration
bench --site yoursite migrate
bench --site yoursite clear-cache
bench restart
```

## After install
1. Open `Razorpay Integration Settings`
2. Set:
   - Provider enabled
   - Test or Live mode
   - Razorpay Integration API Key ID
   - Razorpay Integration API Secret
   - Razorpay Integration Webhook Secret
   - Default company
   - Default advance / receivable accounts
   - Default mode of payment
3. Turn on doctypes you want:
   - Lead
   - Patient Encounter
   - Sales Order
   - Sales Invoice
4. Run provider connection test
5. Verify setup via:
   - `/api/method/razorpay_integration.api.setup.get_setup_status`
   - `/api/method/razorpay_integration.api.setup.smoke_check`
6. Copy webhook URL and register it in Razorpay Integration dashboard
7. Create a payment request from any enabled doctype

## Razorpay Integration webhook
Point Razorpay Integration webhook to:

```text
/api/method/razorpay_integration.api.webhooks.razorpay
```

## Recommended first test order
1. Sales Invoice payment request
2. Patient Encounter advance request
3. Sales Order advance request
4. Lead advance request

## What to verify
- Payment Intent created
- payment link opens correctly
- webhook fires
- Payment Provider Event created
- Payment Entry created or linked
- invoice allocation created where applicable
- doctype summary fields update

## Practical note
`Patient Encounter` support assumes the Healthcare domain exists on the target site. If it does not, test Lead / Sales Order / Sales Invoice first.
