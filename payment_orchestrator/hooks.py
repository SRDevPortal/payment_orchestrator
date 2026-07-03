app_name = "payment_orchestrator"
app_title = "Payment Orchestrator"
app_publisher = "OpenClaw"
app_description = "Multi-gateway payment links, POS collections, webhooks, and ERPNext allocation for Frappe"
app_email = "support@example.com"
app_license = "MIT"

app_include_css = "/assets/payment_orchestrator/css/payment_orchestrator.css"

fixtures = []

after_install = "payment_orchestrator.setup.install.after_install"

doctype_js = {
    "CRM Lead": "public/js/reference_doctypes.js",
    "Patient Encounter": "public/js/reference_doctypes.js",
    "Sales Order": "public/js/reference_doctypes.js",
    "Sales Invoice": "public/js/reference_doctypes.js",
}

doctype_list_js = {
    "Payment Intent": "public/js/payment_intent_list.js",
}

scheduler_events = {
    "daily": [
        "payment_orchestrator.payment_orchestrator.doctype.payment_orchestrator_settings.payment_orchestrator_settings.ensure_single"
    ],
    "hourly": [
        "payment_orchestrator.api.sync.run_periodic_sync"
    ]
}

override_whitelisted_methods = {}

doc_events = {
    "CRM Lead": {
        "on_update": "payment_orchestrator.api.allocations.sync_reference_summary"
    },
    "Sales Invoice": {
        "on_update": "payment_orchestrator.api.allocations.sync_reference_summary"
    },
    "Sales Order": {
        "on_update": "payment_orchestrator.api.allocations.sync_reference_summary"
    },
    "Patient Encounter": {
        "on_update": "payment_orchestrator.api.allocations.sync_reference_summary"
    }
}
