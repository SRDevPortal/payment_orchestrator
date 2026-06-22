# Razorpay Integration - Phased Aggressive Architecture

## Objective
Implement a unified payment orchestration layer for ERPNext that supports payment requests from Lead, Patient Encounter, Sales Order, and Sales Invoice while preserving clean accounting treatment for advances, allocations, and invoice settlement.

## Guiding Rules
- Lead requests default to `Advance`.
- Patient Encounter requests default to `Advance`.
- Sales Order requests default to `Advance`.
- Sales Invoice requests default to `Against Invoice`.
- Encounter advances should auto-settle invoice(s) created from the same encounter when enabled.
- Sales Order advances should auto-settle invoice(s) created from the same order when enabled.
- Lead advances remain unallocated until mapped to downstream business objects.

## Data Model
### Razorpay Integration Settings
Single settings doctype controlling:
- provider mode and credentials
- feature flags
- doctype-level enablement and request-type defaults
- allocation behavior
- accounting defaults
- UI behavior

### Payment Intent
Canonical collection request object linking a payment request to one ERP reference object and provider-side identifiers.

### Payment Allocation
Tracks how collected money is allocated from intent/payment entry to target business objects.

### Payment Provider Event
Stores webhook and provider event payloads for verification, idempotency, and audit.

## Phase 1
- settings doctype
- doctype-level action toggles
- payment intent creation
- Razorpay Integration payment link integration
- webhook receiver
- payment entry creation on success
- invoice binding and advance receipt handling

## Phase 2
- auto allocation engine
- encounter->invoice auto settlement
- sales order->invoice auto settlement
- lead conversion carry-forward flow
- refund processing
- payment summaries on reference doctypes

## Phase 3
- settlement sync
- analytics and operational dashboards
- reminder automation
- checkout/order flow support in addition to payment links
- richer role-based visibility and controls
