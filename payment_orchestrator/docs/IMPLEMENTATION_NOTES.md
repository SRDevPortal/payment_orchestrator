# Implementation Notes

## Immediate next build steps
1. Wire provider credential validation and test connection action.
2. Implement real Razorpay Payment Links API call.
3. Add webhook endpoint with signature verification.
4. Create Payment Entry generation service.
5. Add reference-doctype helper to derive party context.
6. Add summary dashboard cards on CRM Lead / Encounter / Sales Order / Sales Invoice.
7. Implement allocation engine and allocation logs.

## Important guardrails
- Never log key secrets or webhook secrets.
- Store raw webhook payloads only with access control.
- Make webhook processing idempotent.
- Payment Entry creation must be retry-safe.
- Keep ERPNext as the source of truth for invoice and accounting state.
