# Payment Orchestrator - Smoke Test

## Goal
Verify that the app is installable and first-run configuration is usable before full UAT.

## Bench steps

```bash
bench --site yoursite install-app payment_orchestrator
bench --site yoursite migrate
bench --site yoursite clear-cache
bench restart
```

## App checks

### 1. Settings exists
Open:
- `Payment Orchestrator Settings`

Expected:
- single settings record opens successfully

### 2. Setup status API
Call:
```text
/api/method/payment_orchestrator.api.setup.get_setup_status
```

Expected:
- returns provider mode, webhook URL, enabled doctypes, and record counts

### 3. Smoke check API
Call:
```text
/api/method/payment_orchestrator.api.setup.smoke_check
```

Expected:
- returns structured checks for keys, webhook, and core doctypes

### 4. Provider connection
Use the settings page helper or call:
```text
/api/method/payment_orchestrator.api.settings.test_provider_connection
```

Expected:
- valid Razorpay response if credentials are correct

### 5. Payment request
Create a payment request from one enabled reference doctype.

Expected:
- `Payment Intent` created
- payment link URL stored
- summary fields update on source record

### 6. Webhook
Trigger a real or test webhook from Razorpay.

Expected:
- `Payment Provider Event` created
- duplicate guard works on repeated payloads
- payment intent/payment entry update path executes

## Notes
- `Patient Encounter` validation depends on Healthcare being installed on the target site.
- If your site uses custom account fields or custom invoice flows, those may still need site-specific hardening after UAT.
