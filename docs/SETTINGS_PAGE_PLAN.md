# Razorpay Integration Settings Page Plan

## Goal
Provide a central control plane for collections so business and finance users can enable or disable payment generation by ERP doctype without code changes.

## Sections
1. Provider Configuration
   - enable provider
   - mode: Test/Live
   - API Key ID
   - API Key Secret
   - Webhook Secret
   - API Base URL
   - Default Company
   - Payment Gateway Label

2. Feature Flags
   - enable payment links
   - enable checkout/orders
   - enable refunds
   - enable webhook processing
   - enable auto allocation
   - enable settlement sync

3. Doctype-Level Controls
   - Lead: on/off, default request type, partial payments
   - Patient Encounter: on/off, default request type, partial payments
   - Sales Order: on/off, default request type, partial payments
   - Sales Invoice: on/off, default request type, partial payments

4. Allocation & Accounting Behavior
   - encounter advance auto allocation
   - sales order advance auto allocation
   - invoice binding
   - overpayment policy
   - excess as unallocated credit
   - default advance account
   - default receivable account
   - default cost center

5. UI & Action Controls
   - show action buttons
   - show payment summary widgets
   - allow manual regenerate payment link
   - show provider debug info

## Why this matters
This settings page prevents hardcoded business logic and lets operations decide where collections are allowed without developer intervention.
