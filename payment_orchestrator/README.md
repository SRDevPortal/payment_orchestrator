# Payment Orchestrator

Unified payment collection and allocation layer for ERPNext/Frappe.

## Goal
Provide a single payment intent model across Lead, Patient Encounter, Sales Order, and Sales Invoice with Payment Orchestrator as the first provider.

## Current capabilities
- `Payment Orchestrator Settings` single doctype
- `Payment Intent`, `Payment Allocation`, and `Payment Provider Event` doctypes
- Payment Orchestrator payment-link creation
- webhook verification and duplicate guard
- Payment Entry creation/allocation flow scaffolding
- per-reference summary sync for Lead / Encounter / Sales Order / Sales Invoice
- settings page helper UI
- setup status and smoke-check APIs

## Install
```bash
cd $PATH_TO_YOUR_BENCH
bench get-app /Users/admin/.openclaw/workspace/razorpay
bench --site yoursite install-app payment_orchestrator
bench --site yoursite migrate
```

## First-run flow
1. Open `Payment Orchestrator Settings`
2. Fill Payment Orchestrator credentials and webhook secret
3. Set company/accounts/mode of payment defaults
4. Enable the reference doctypes you want
5. Run provider connection test
6. Register the webhook URL in Payment Orchestrator
7. Create a payment request from an enabled doctype

## Important boundary
The app is now close to plug-and-play from the code side, but real success still depends on your live ERPNext accounting mappings, site doctypes, Payment Orchestrator credentials, and webhook reachability.
