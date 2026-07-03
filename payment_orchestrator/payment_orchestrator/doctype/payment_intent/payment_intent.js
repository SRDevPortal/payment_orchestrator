frappe.ui.form.on('Payment Intent', {
    refresh(frm) {
        render_payment_intent_overview(frm);
        add_gateway_actions(frm);
        add_admin_correction_button(frm);

        const locked_statuses = [
            'Paid',
            'Partially Allocated',
            'Allocated',
            'Refunded',
            'Cancelled',
            'Expired',
        ];
        const locked = locked_statuses.includes(frm.doc.status);

        if (!locked) return;

        frm.disable_save();
        Object.keys(frm.fields_dict || {}).forEach((fieldname) => {
            const field = frm.fields_dict[fieldname];
            const fieldtype = field && field.df && field.df.fieldtype;
            if (['Section Break', 'Column Break', 'Tab Break', 'HTML'].includes(fieldtype)) {
                return;
            }
            frm.set_df_property(fieldname, 'read_only', 1);
        });
    },
});

function render_payment_intent_overview(frm) {
    if (frm.is_new()) return;

    const doc = frm.doc || {};
    const payload = parse_provider_payload(doc.provider_payload_snapshot);
    const txn = extract_transaction_details(payload);
    const status = classify_intent_status(doc);
    const provider = classify_provider_status(doc);
    const error_hint = provider.kind === 'danger' ? payment_error_hint(provider.label) : '';

    const html = `
        <div class="po-intent-overview">
            <div class="po-intent-header">
                <div>
                    <div class="po-intent-title">${escape_html(doc.name)}</div>
                    <div class="po-intent-subtitle">
                        ${escape_html(doc.reference_doctype || '')} ${escape_html(doc.reference_name || '')}
                    </div>
                </div>
                <div class="po-badge-row">
                    ${badge(doc.gateway || 'Gateway', gateway_badge_kind(doc.gateway))}
                    ${badge(doc.payment_mode || 'Mode', 'neutral')}
                    ${badge(doc.provider_mode || 'Mode', doc.provider_mode === 'Live' ? 'danger-soft' : 'info-soft')}
                </div>
            </div>
            <div class="po-badge-row po-intent-status-row">
                ${badge(doc.status || 'Draft', status.kind)}
                ${badge(doc.allocation_status || 'Unallocated', allocation_badge_kind(doc.allocation_status))}
                ${badge(provider.label, provider.kind)}
            </div>
            ${error_hint ? `<div class="po-intent-alert po-intent-alert-danger">${escape_html(error_hint)}</div>` : ''}
            <div class="po-intent-grid">
                ${metric(__('Requested'), format_currency_value(doc.amount_requested, doc.currency))}
                ${metric(__('Paid'), format_currency_value(doc.amount_paid, doc.currency))}
                ${metric(__('Allocated'), format_currency_value(doc.amount_allocated, doc.currency))}
                ${metric(__('Unallocated'), format_currency_value(doc.amount_unallocated, doc.currency))}
            </div>
            <div class="po-intent-links">
                ${link_item(__('Sales Invoice'), 'Sales Invoice', doc.sales_invoice)}
                ${link_item(__('Payment Entry'), 'Payment Entry', doc.payment_entry)}
                ${link_item(__('Reference'), doc.reference_doctype, doc.reference_name)}
            </div>
            ${transaction_panel(doc, txn)}
        </div>
    `;

    const dashboard = frm.dashboard && (frm.dashboard.wrapper || frm.dashboard.parent);
    if (!dashboard) return;
    $(dashboard).find('.po-intent-overview').closest('.form-dashboard-section').remove();
    frm.dashboard.add_section(html, __('Payment Overview'));
}

function add_gateway_actions(frm) {
    if (frm.is_new()) return;

    if (frm.doc.gateway === 'Pine Labs' && frm.doc.payment_mode === 'POS' && frm.doc.provider_pos_request_id) {
        frm.add_custom_button(__('Fetch POS Status'), () => {
            frappe.call({
                method: 'payment_orchestrator.api.pinelabs.fetch_pos_payment_status',
                args: { payment_intent: frm.doc.name },
                freeze: true,
                freeze_message: __('Fetching POS status...'),
                callback() {
                    frm.reload_doc();
                },
            });
        }, __('Gateway Actions'));
    }

    if (frm.doc.gateway === 'Razorpay' && frm.doc.payment_mode === 'Payment Link' && frm.doc.provider_link_id) {
        frm.add_custom_button(__('Fetch Payment Link'), () => {
            frappe.call({
                method: 'payment_orchestrator.api.razorpay.fetch_payment_link',
                args: { payment_intent: frm.doc.name },
                freeze: true,
                freeze_message: __('Fetching payment link...'),
                callback() {
                    frm.reload_doc();
                },
            });
        }, __('Gateway Actions'));
    }

    if (frm.doc.payment_link_url) {
        frm.add_custom_button(__('Open Payment Link'), () => {
            window.open(frm.doc.payment_link_url, '_blank', 'noopener');
        }, __('Gateway Actions'));
    }

    if (frm.doc.gateway === 'Razorpay' && frm.doc.payment_mode === 'QR Code' && frm.doc.provider_qr_id) {
        frm.add_custom_button(__('Fetch QR Status'), () => {
            frappe.call({
                method: 'payment_orchestrator.api.razorpay.fetch_qr_code',
                args: { payment_intent: frm.doc.name },
                freeze: true,
                freeze_message: __('Fetching QR status...'),
                callback() {
                    frm.reload_doc();
                },
            });
        }, __('Gateway Actions'));

        frm.add_custom_button(__('Close QR'), () => {
            frappe.confirm(__('Close this Razorpay QR Code?'), () => {
                frappe.call({
                    method: 'payment_orchestrator.api.razorpay.close_qr_code',
                    args: { payment_intent: frm.doc.name },
                    freeze: true,
                    freeze_message: __('Closing QR code...'),
                    callback() {
                        frm.reload_doc();
                    },
                });
            });
        }, __('Gateway Actions'));
    }

    if (frm.doc.qr_code_url) {
        frm.add_custom_button(__('Open QR'), () => {
            window.open(frm.doc.qr_code_url, '_blank', 'noopener');
        }, __('Gateway Actions'));
    }
}

function add_admin_correction_button(frm) {
    if (frm.is_new()) return;
    const roles = frappe.user_roles || [];
    if (!roles.includes('System Manager') && !roles.includes('Payment Orchestrator Manager')) {
        return;
    }

    frm.add_custom_button(__('Admin Correction'), () => {
        const dialog = new frappe.ui.Dialog({
            title: __('Payment Intent Admin Correction'),
            fields: [
                {
                    label: __('Correction Type'),
                    fieldname: 'correction_type',
                    fieldtype: 'Select',
                    reqd: 1,
                    options: [
                        'refresh_summary',
                        'link_sales_invoice',
                        'unlink_sales_invoice',
                        'link_payment_entry',
                        'unlink_payment_entry',
                        'mark_expired',
                        'mark_cancelled',
                    ].join('\n'),
                },
                {
                    label: __('Sales Invoice'),
                    fieldname: 'sales_invoice',
                    fieldtype: 'Link',
                    options: 'Sales Invoice',
                    depends_on: "eval:['link_sales_invoice'].includes(doc.correction_type)",
                },
                {
                    label: __('Payment Entry'),
                    fieldname: 'payment_entry',
                    fieldtype: 'Link',
                    options: 'Payment Entry',
                    depends_on: "eval:['link_payment_entry'].includes(doc.correction_type)",
                },
                {
                    label: __('Force'),
                    fieldname: 'force',
                    fieldtype: 'Check',
                    depends_on: "eval:['link_payment_entry'].includes(doc.correction_type)",
                    description: __('Allowed only when amount and party match. It does not move accounting allocations.'),
                },
                {
                    label: __('Reason'),
                    fieldname: 'reason',
                    fieldtype: 'Small Text',
                    reqd: 1,
                },
            ],
            primary_action_label: __('Apply Correction'),
            primary_action(values) {
                frappe.call({
                    method: 'payment_orchestrator.api.corrections.apply_payment_intent_correction',
                    args: {
                        payment_intent: frm.doc.name,
                        correction_type: values.correction_type,
                        reason: values.reason,
                        sales_invoice: values.sales_invoice,
                        payment_entry: values.payment_entry,
                        force: values.force ? 1 : 0,
                    },
                    freeze: true,
                    freeze_message: __('Applying correction...'),
                    callback(r) {
                        const message = r.message || {};
                        dialog.hide();
                        frappe.show_alert({
                            message: __('Correction applied: {0}', [message.correction_log || '']),
                            indicator: 'green',
                        }, 8);
                        frm.reload_doc();
                    },
                });
            },
        });
        dialog.show();
    }, __('Payment Actions'));
}

function parse_provider_payload(raw) {
    if (!raw) return {};
    try {
        return JSON.parse(raw);
    } catch (e) {
        return {};
    }
}

function extract_transaction_details(payload) {
    const rows = {};
    (payload.TransactionData || []).forEach((row) => {
        if (row && row.Tag) rows[row.Tag] = row.Value;
    });
    return rows;
}

function classify_intent_status(doc) {
    const status = String(doc.status || '').toLowerCase();
    if (['allocated', 'paid'].includes(status)) return { kind: 'success' };
    if (['partially allocated', 'partially paid'].includes(status)) return { kind: 'info' };
    if (['expired'].includes(status)) return { kind: 'warning' };
    if (['cancelled', 'refunded'].includes(status)) return { kind: 'neutral' };
    return { kind: 'pending' };
}

function classify_provider_status(doc) {
    const raw = doc.pos_failure_reason || doc.payment_status || doc.pos_request_status || doc.qr_status || doc.status || '';
    const value = String(raw || '').trim();
    const lower = value.toLowerCase();
    if (!value) return { label: __('No Provider Status'), kind: 'neutral' };
    if (
        lower.includes('invalid') ||
        lower.includes('failed') ||
        lower.includes('error') ||
        lower.includes('declined') ||
        lower.includes('reject')
    ) {
        return { label: value, kind: 'danger' };
    }
    if (lower.includes('approved') || lower.includes('captured') || lower === 'paid' || lower === 'processed') {
        return { label: value, kind: 'success' };
    }
    if (lower.includes('expired') || lower.includes('closed')) return { label: value, kind: 'warning' };
    if (lower.includes('cancel')) return { label: value, kind: 'neutral' };
    if (lower.includes('uploaded') || lower.includes('requested') || lower.includes('active')) {
        return { label: value, kind: 'pending' };
    }
    return { label: value, kind: 'info' };
}

function gateway_badge_kind(gateway) {
    if (gateway === 'Pine Labs') return 'pine';
    if (gateway === 'Razorpay') return 'razorpay';
    return 'neutral';
}

function allocation_badge_kind(status) {
    const value = String(status || '').toLowerCase();
    if (value.includes('fully')) return 'success';
    if (value.includes('partial')) return 'info';
    return 'neutral';
}

function payment_error_hint(message) {
    const value = String(message || '').toUpperCase();
    if (value.includes('INVALID CLIENT')) return __('Pine Labs rejected the POS ID / Client ID. Verify it is mapped to the Merchant ID and Store ID.');
    if (value.includes('INVALID MERCHANT')) return __('Pine Labs rejected the merchant setup. Verify Merchant ID, Store ID, Security Token, and production/UAT base URL.');
    if (value.includes('OPEN TXN')) return __('Pine Labs has an open transaction on this terminal. Approve or cancel it on the POS device first.');
    return __('Provider reported a failed transaction. Check the provider response and gateway setup.');
}

function badge(label, kind) {
    return `<span class="po-status-badge po-status-${escape_attr(kind || 'neutral')}">${escape_html(label || '')}</span>`;
}

function metric(label, value) {
    return `
        <div class="po-intent-metric">
            <div class="po-intent-metric-label">${escape_html(label)}</div>
            <div class="po-intent-metric-value">${escape_html(value)}</div>
        </div>
    `;
}

function link_item(label, doctype, name) {
    if (!doctype || !name) return '';
    const href = `/app/${frappe.router.slug(doctype)}/${encodeURIComponent(name)}`;
    return `<a class="po-intent-link" href="${href}"><span>${escape_html(label)}</span><b>${escape_html(name)}</b></a>`;
}

function transaction_panel(doc, txn) {
    const rows = [
        [__('POS Request ID'), doc.provider_pos_request_id],
        [__('Terminal / Client ID'), doc.provider_terminal_id],
        [__('POS Payment Method'), doc.pos_payment_method],
        [__('Allowed Payment Mode Code'), doc.pos_allowed_payment_mode],
        [__('Provider Payment ID'), doc.provider_payment_id],
        [__('Payment Mode'), txn.PaymentMode],
        [__('RRN'), txn.RRN],
        [__('Approval Code'), txn.ApprovalCode],
        [__('Card Type'), txn['Card Type']],
        [__('Transaction Date'), format_pinelabs_date_time(txn['Transaction Date'], txn['Transaction Time'])],
    ].filter((row) => row[1]);

    if (!rows.length) return '';

    return `
        <div class="po-intent-panel">
            <div class="po-intent-panel-title">${escape_html(__('Transaction Details'))}</div>
            <div class="po-intent-detail-grid">
                ${rows.map(([label, value]) => `
                    <div class="po-intent-detail">
                        <span>${escape_html(label)}</span>
                        <b>${escape_html(value)}</b>
                    </div>
                `).join('')}
            </div>
        </div>
    `;
}

function format_currency_value(value, currency) {
    const amount = Number(value || 0);
    if (frappe.format) {
        return frappe.format(amount, { fieldtype: 'Currency', options: currency || 'INR' });
    }
    return `${currency || 'INR'} ${amount.toFixed(2)}`;
}

function format_pinelabs_date_time(date, time) {
    if (!date && !time) return '';
    const raw_date = String(date || '');
    const raw_time = String(time || '').padStart(6, '0');
    if (raw_date.length !== 8) return `${raw_date} ${raw_time}`.trim();
    return `${raw_date.slice(0, 2)}-${raw_date.slice(2, 4)}-${raw_date.slice(4)} ${raw_time.slice(0, 2)}:${raw_time.slice(2, 4)}:${raw_time.slice(4)}`;
}

function escape_html(value) {
    return frappe.utils.escape_html(String(value || ''));
}

function escape_attr(value) {
    return escape_html(value).replace(/"/g, '&quot;');
}
