app_name = "razorpay_integration"
app_title = "Pine Labs"
app_publisher = "OpenClaw"
app_description = "Pine Labs payment collection and allocation layer for ERPNext/Frappe"
app_email = "support@example.com"
app_license = "MIT"

app_include_css = "/assets/razorpay_integration/css/payment_orchestrator.css"
app_include_js = "/assets/razorpay_integration/js/reference_doctypes.js"

fixtures = []

after_install = "razorpay_integration.setup.install.after_install"

doctype_js = {
    "Lead": "public/js/reference_doctypes.js",
    "Patient Encounter": "public/js/reference_doctypes.js",
    "Sales Order": "public/js/reference_doctypes.js",
    "Sales Invoice": "public/js/reference_doctypes.js",
}

scheduler_events = {
    "daily": [
        "razorpay_integration.razorpay_integration.doctype.razorpay_integration_settings.razorpay_integration_settings.ensure_single"
    ],
    "hourly": [
        "razorpay_integration.api.sync.run_periodic_sync"
    ]
}

override_whitelisted_methods = {}

doc_events = {
    "Sales Invoice": {
        "on_update": "razorpay_integration.api.allocations.sync_reference_summary"
    },
    "Sales Order": {
        "on_update": "razorpay_integration.api.allocations.sync_reference_summary"
    },
    "Patient Encounter": {
        "on_update": "razorpay_integration.api.allocations.sync_reference_summary"
    },
    "Lead": {
        "on_update": "razorpay_integration.api.allocations.sync_reference_summary"
    }
}
