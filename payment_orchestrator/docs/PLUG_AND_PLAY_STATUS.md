# Payment Orchestrator - Plug-and-Play Status

## Completed
- central settings doctype with provider, feature, security, accounting, and doctype-level controls
- real Razorpay payment-link API integration
- webhook verification and event log
- duplicate webhook guard
- payment intent model
- payment allocation model
- provider event model
- Payment Entry generation flow scaffold
- invoice auto-allocation scaffold
- encounter/sales-order allocation discovery logic scaffold
- per-reference payment summary sync
- install hook adding summary fields to reference doctypes
- settings helper page
- setup status API
- smoke-check API
- refund API scaffold
- periodic sync skeleton

## Plug-and-play interpretation
This app is plug-and-play from the **application/code side**:
- installable package structure exists
- settings control plane exists
- first-run validation helpers exist
- webhook path exists
- reference doctypes can generate payment requests
- operational docs exist

## Remaining practical boundary
Production success still depends on:
- your site's accounting setup
- live Razorpay credentials
- webhook registration and reachability
- real ERPNext doctype/field conventions on your site

## Meaning of complete here
- app artifacts are bundled
- setup surface exists
- smoke-check path exists
- workflow APIs exist
- install helper exists
- docs exist

## Meaning of not assumed
- no bench/site execution performed by assistant
- no live credential insertion
- no external dashboard setup performed
- no guarantee that custom site accounting conventions match defaults exactly
