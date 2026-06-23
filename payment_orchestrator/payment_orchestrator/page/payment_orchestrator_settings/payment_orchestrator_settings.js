frappe.pages['payment-orchestrator-settings'].on_page_load = function(wrapper) {
    frappe.ui.make_app_page({
        parent: wrapper,
        title: 'Payment Orchestrator Settings',
        single_column: true
    });

    const body = `
        <div class="payment-orchestrator-settings-layout" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;">
            <div class="card" style="padding:16px;">
                <h3>Provider Control</h3>
                <p>Configure Razorpay credentials, mode, webhook secret, and API base URL from one place.</p>
                <ul>
                    <li>Test/Live mode</li>
                    <li>API key + secret</li>
                    <li>Webhook secret</li>
                    <li>Provider enable/disable</li>
                </ul>
                <button class="btn btn-primary btn-sm po-test-connection">Test Razorpay Connection</button>
                <div class="po-test-output" style="margin-top:10px;font-size:12px;color:#555;"></div>
            </div>
            <div class="card" style="padding:16px;">
                <h3>Doctype Toggles</h3>
                <p>Turn payment actions on or off independently for Lead, Patient Encounter, Sales Order, and Sales Invoice.</p>
                <ul>
                    <li>Default request type per doctype</li>
                    <li>Partial payment control</li>
                    <li>Auto allocation behavior</li>
                </ul>
            </div>
            <div class="card" style="padding:16px;">
                <h3>Allocation + Security</h3>
                <p>Control duplicate webhook protection, payload storage, accounting defaults, and allocation behavior.</p>
                <button class="btn btn-secondary btn-sm po-copy-webhook">Copy Webhook URL</button>
                <div class="po-webhook-output" style="margin-top:10px;font-size:12px;color:#555;"></div>
            </div>
        </div>
    `;

    $(wrapper).html(body);

    $(wrapper).find('.po-test-connection').on('click', function() {
        const output = $(wrapper).find('.po-test-output');
        output.text('Testing connection...');
        frappe.call({
            method: 'payment_orchestrator.api.settings.test_provider_connection',
            freeze: true,
            freeze_message: __('Testing Razorpay connection...'),
            callback(r) {
                const msg = r.message || {};
                output.html(`✅ ${msg.message || 'Connection test complete.'}<br>Webhook URL: ${msg.webhook_url || ''}`);
                $(wrapper).data('webhook-url', msg.webhook_url || '');
            },
            error() {
                output.text('Connection test failed. Check credentials and server logs.');
            }
        });
    });

    $(wrapper).find('.po-copy-webhook').on('click', function() {
        const url = $(wrapper).data('webhook-url');
        const output = $(wrapper).find('.po-webhook-output');
        if (!url) {
            output.text('Run Test Razorpay Connection first to fetch webhook URL.');
            return;
        }
        navigator.clipboard.writeText(url).then(() => {
            output.text(`Copied: ${url}`);
        }).catch(() => {
            output.text(url);
        });
    });
};
