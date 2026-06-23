frappe.provide('payment_orchestrator');

payment_orchestrator.get_settings_context = function(callback) {
    frappe.call({
        method: 'payment_orchestrator.api.settings.get_settings_context',
        callback(r) {
            callback(r.message || {});
        }
    });
};

payment_orchestrator.is_doctype_enabled = function(frm, settings) {
    const mapping = {
        'CRM Lead': settings.enable_on_crm_lead,
        'Patient Encounter': settings.enable_on_patient_encounter,
        'Sales Order': settings.enable_on_sales_order,
        'Sales Invoice': settings.enable_on_sales_invoice,
    };
    return !!mapping[frm.doctype];
};

payment_orchestrator.get_pos_context = function(callback) {
    frappe.call({
        method: 'payment_orchestrator.api.pos.get_pos_context',
        callback(r) {
            callback(r.message || {});
        }
    });
};

payment_orchestrator.payment_watchers = payment_orchestrator.payment_watchers || {};

payment_orchestrator.is_payment_complete = function(intent) {
    if (!intent) return false;
    const status = String(intent.status || '').toLowerCase();
    const provider_status = String(intent.payment_status || '').toLowerCase();
    return (
        ['paid', 'allocated', 'partially allocated'].includes(status) ||
        ['captured', 'paid'].includes(provider_status) ||
        parseFloat(intent.amount_paid || 0) > 0
    );
};

payment_orchestrator.stop_payment_watcher = function(payment_intent) {
    const watcher = payment_orchestrator.payment_watchers[payment_intent];
    if (!watcher) return;

    watcher.stopped = true;
    if (watcher.interval) clearInterval(watcher.interval);
    if (watcher.timeout) clearTimeout(watcher.timeout);
    if (watcher.realtime_handler && frappe.realtime && frappe.realtime.off) {
        frappe.realtime.off('payment_orchestrator_payment_completed', watcher.realtime_handler);
    }
    delete payment_orchestrator.payment_watchers[payment_intent];
};

payment_orchestrator.watch_payment_completion = function(payment_intent, options) {
    if (!payment_intent) return;
    const opts = options || {};
    const dialog = opts.dialog;
    const frm = opts.frm;
    const timeout_ms = opts.timeout_ms || 10 * 60 * 1000;

    payment_orchestrator.stop_payment_watcher(payment_intent);

    const watcher = { stopped: false };
    payment_orchestrator.payment_watchers[payment_intent] = watcher;

    const complete = function(data) {
        if (watcher.stopped) return;
        payment_orchestrator.stop_payment_watcher(payment_intent);

        if (dialog && dialog.hide) {
            dialog.hide();
        }
        frappe.show_alert({
            message: __('Payment received and allocated'),
            indicator: 'green'
        }, 8);
        if (frm && frm.reload_doc) {
            frm.reload_doc();
        }
    };

    const poll = function() {
        if (watcher.stopped) return;
        frappe.call({
            method: 'payment_orchestrator.api.intents.get_payment_intent',
            args: { payment_intent },
            callback(r) {
                const intent = r.message || {};
                if (payment_orchestrator.is_payment_complete(intent)) {
                    complete(intent);
                }
            }
        });
    };

    watcher.realtime_handler = function(data) {
        if ((data || {}).payment_intent === payment_intent) {
            complete(data);
        }
    };
    if (frappe.realtime && frappe.realtime.on) {
        frappe.realtime.on('payment_orchestrator_payment_completed', watcher.realtime_handler);
    }

    watcher.interval = setInterval(poll, 3000);
    watcher.timeout = setTimeout(() => payment_orchestrator.stop_payment_watcher(payment_intent), timeout_ms);
    setTimeout(poll, 1500);

    if (dialog && dialog.$wrapper) {
        dialog.$wrapper.on('hidden.bs.modal', () => payment_orchestrator.stop_payment_watcher(payment_intent));
    }
};

payment_orchestrator.render_dashboard = function(frm) {
    frappe.call({
        method: 'payment_orchestrator.api.dashboard.get_reference_dashboard',
        args: {
            reference_doctype: frm.doctype,
            reference_name: frm.doc.name,
        },
        callback(r) {
            const data = r.message || {};
            const summary = data.summary || {};
            const intents = data.intents || [];
            const html = `
                <div class="po-dashboard card" style="padding:12px;margin-top:12px;">
                    <div style="display:flex;gap:24px;flex-wrap:wrap;">
                        <div><div style="font-size:11px;color:#777;">Requested</div><div style="font-size:18px;font-weight:600;">${summary.total_requested || 0}</div></div>
                        <div><div style="font-size:11px;color:#777;">Paid</div><div style="font-size:18px;font-weight:600;">${summary.total_paid || 0}</div></div>
                        <div><div style="font-size:11px;color:#777;">Allocated</div><div style="font-size:18px;font-weight:600;">${summary.total_allocated || 0}</div></div>
                        <div><div style="font-size:11px;color:#777;">Unallocated</div><div style="font-size:18px;font-weight:600;">${summary.total_unallocated || 0}</div></div>
                    </div>
                    <hr>
                    <div><b>Recent Payment Intents</b></div>
                    <div style="margin-top:8px;max-height:220px;overflow:auto;">
                        ${intents.length ? intents.map(row => `<div style="padding:8px 0;border-bottom:1px solid #eee;"><div><b>${row.name}</b> - ${row.status}</div><div style="font-size:12px;color:#666;">${row.gateway || ''} ${row.payment_mode || ''} | ${row.request_type} | Requested: ${row.amount_requested} | Paid: ${row.amount_paid} | Allocated: ${row.amount_allocated}</div>${row.payment_link_url ? `<div style="font-size:12px;"><a href="${row.payment_link_url}" target="_blank">Open Payment Link</a></div>` : ''}${row.qr_code_url ? `<div style="font-size:12px;"><a href="${row.qr_code_url}" target="_blank">Open QR Code</a></div>` : ''}</div>`).join('') : '<div style="color:#666;">No payment intents yet.</div>'}
                    </div>
                </div>
            `;
            if (!frm.fields_dict.po_payment_dashboard_html) {
                frm.dashboard.add_section(html, __('Payments'));
            } else {
                frm.fields_dict.po_payment_dashboard_html.$wrapper.html(html);
            }
        }
    });
};

payment_orchestrator.add_request_payment_button = function(frm, settings) {
    if (frm.is_new && !frm.doc.name) return;
    if (!settings.show_action_buttons || !payment_orchestrator.is_doctype_enabled(frm, settings)) return;

    if (settings.enable_razorpay_payment_link) {
        frm.add_custom_button(__('Razorpay Payment Link'), function() {
        const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
        const dialog = new frappe.ui.Dialog({
            title: __('Razorpay Payment Link'),
            fields: [
                { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                { label: __('Request Type'), fieldname: 'request_type', fieldtype: 'Select', options: 'Advance\nAgainst Invoice', default: frm.doctype === 'Sales Invoice' ? 'Against Invoice' : 'Advance' },
                { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
            ],
            primary_action_label: __('Generate Payment Link'),
            primary_action(values) {
                frappe.call({
                    method: 'payment_orchestrator.api.intents.create_payment_intent',
                    args: {
                        reference_doctype: frm.doctype,
                        reference_name: frm.doc.name,
                        amount: values.amount,
                        request_type: values.request_type,
                        notes: values.notes,
                    },
                    freeze: true,
                    freeze_message: __('Generating Razorpay payment link...'),
                    callback(r) {
                        const data = r.message || {};
                        dialog.hide();
                        if (data.payment_link_url) {
                            frappe.msgprint({
                                title: __('Payment Link Created'),
                                message: `<div><p>${__('Payment Intent')}: <b>${data.payment_intent}</b></p><p><a href="${data.payment_link_url}" target="_blank">${data.payment_link_url}</a></p></div>`,
                                indicator: 'green'
                            });
                            payment_orchestrator.watch_payment_completion(data.payment_intent, {
                                frm,
                                dialog: frappe.msg_dialog
                            });
                        }
                        frm.reload_doc();
                    }
                });
            }
        });
        dialog.show();
        }, __('Payments'));
    }

    if (settings.enable_razorpay_qr_code && ['Patient Encounter', 'Sales Order', 'Sales Invoice'].includes(frm.doctype)) {
        frm.add_custom_button(__('Razorpay QR Code'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
            const dialog = new frappe.ui.Dialog({
                title: __('Razorpay QR Code'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    { label: __('Request Type'), fieldname: 'request_type', fieldtype: 'Select', options: 'Advance\nAgainst Invoice', default: frm.doctype === 'Sales Invoice' ? 'Against Invoice' : 'Advance' },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
                ],
                primary_action_label: __('Generate QR Code'),
                primary_action(values) {
                    frappe.call({
                        method: 'payment_orchestrator.api.intents.create_razorpay_qr_code',
                        args: {
                            reference_doctype: frm.doctype,
                            reference_name: frm.doc.name,
                            amount: values.amount,
                            request_type: values.request_type,
                            notes: values.notes,
                        },
                        freeze: true,
                        freeze_message: __('Generating Razorpay QR code...'),
                        callback(r) {
                            const data = r.message || {};
                            dialog.hide();
                            if (data.qr_code_url) {
                                const url = frappe.utils.escape_html(data.qr_code_url);
                                frappe.msgprint({
                                    title: __('QR Code Created'),
                                    message: `<div><p>${__('Payment Intent')}: <b>${frappe.utils.escape_html(data.payment_intent || '')}</b></p><p><a href="${url}" target="_blank">${url}</a></p><div style="margin-top:12px;"><img src="${url}" style="max-width:260px;width:100%;height:auto;border:1px solid #e5e7eb;padding:8px;border-radius:6px;background:#fff;"></div></div>`,
                                    indicator: 'green'
                                });
                                payment_orchestrator.watch_payment_completion(data.payment_intent, {
                                    frm,
                                    dialog: frappe.msg_dialog
                                });
                            }
                            frm.reload_doc();
                        }
                    });
                }
            });
            dialog.show();
        }, __('Payments'));
    }

    if (settings.enable_pinelabs_payment_link) {
        frm.add_custom_button(__('Pine Labs Payment Link'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
            const dialog = new frappe.ui.Dialog({
                title: __('Pine Labs Payment Link'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    { label: __('Request Type'), fieldname: 'request_type', fieldtype: 'Select', options: 'Advance\nAgainst Invoice', default: frm.doctype === 'Sales Invoice' ? 'Against Invoice' : 'Advance' },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
                ],
                primary_action_label: __('Generate Payment Link'),
                primary_action(values) {
                    frappe.call({
                        method: 'payment_orchestrator.api.intents.create_gateway_payment_link',
                        args: {
                            reference_doctype: frm.doctype,
                            reference_name: frm.doc.name,
                            amount: values.amount,
                            gateway: 'Pine Labs',
                            request_type: values.request_type,
                            notes: values.notes,
                        },
                        freeze: true,
                        freeze_message: __('Generating Pine Labs payment link...'),
                        callback(r) {
                            const data = r.message || {};
                            dialog.hide();
                            if (data.payment_link_url) {
                                frappe.msgprint({
                                    title: __('Payment Link Created'),
                                    message: `<div><p>${__('Payment Intent')}: <b>${data.payment_intent}</b></p><p><a href="${data.payment_link_url}" target="_blank">${data.payment_link_url}</a></p></div>`,
                                    indicator: 'green'
                                });
                                payment_orchestrator.watch_payment_completion(data.payment_intent, {
                                    frm,
                                    dialog: frappe.msg_dialog
                                });
                            }
                            frm.reload_doc();
                        }
                    });
                }
            });
            dialog.show();
        }, __('Payments'));
    }

    if (settings.enable_pinelabs_pos && frm.doctype === 'Sales Invoice' && frm.doc.docstatus === 1) {
        frm.add_custom_button(__('Pine Labs POS'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || 0;
            const dialog = new frappe.ui.Dialog({
                title: __('Pine Labs POS Payment'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
                ],
                primary_action_label: __('Send to POS'),
                primary_action(values) {
                    frappe.call({
                        method: 'payment_orchestrator.api.pos.request_pos_payment',
                        args: {
                            sales_invoice: frm.doc.name,
                            amount: values.amount,
                            notes: values.notes,
                        },
                        freeze: true,
                        freeze_message: __('Sending payment request to POS machine...'),
                        callback(r) {
                            const data = r.message || {};
                            dialog.hide();
                            frappe.msgprint({
                                title: __('POS Payment Requested'),
                                message: `<div><p>${__('Payment Intent')}: <b>${frappe.utils.escape_html(data.payment_intent || '')}</b></p><p>${__('POS Request')}: <b>${frappe.utils.escape_html(data.provider_pos_request_id || data.pos_request_status || '')}</b></p><p>${__('Terminal')}: <b>${frappe.utils.escape_html(data.terminal_id || '')}</b></p></div>`,
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    });
                }
            });
            dialog.show();
        }, __('Payments'));
    }

    if (settings.enable_pinelabs_pos && ['Patient Encounter', 'Sales Invoice'].includes(frm.doctype)) {
        frm.add_custom_button(__('Pine Labs POS (Demo)'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
            const dialog = new frappe.ui.Dialog({
                title: __('Pine Labs POS Demo'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text', default: 'Demo POS payment' }
                ],
                primary_action_label: __('Mock Paid on POS'),
                primary_action(values) {
                    frappe.call({
                        method: 'payment_orchestrator.api.pos.mock_pos_payment',
                        args: {
                            reference_doctype: frm.doctype,
                            reference_name: frm.doc.name,
                            amount: values.amount,
                            notes: values.notes,
                        },
                        freeze: true,
                        freeze_message: __('Mocking POS payment...'),
                        callback(r) {
                            const data = r.message || {};
                            dialog.hide();
                            frappe.msgprint({
                                title: __('Demo POS Payment Complete'),
                                message: `<div><p>${__('Sales Invoice')}: <b>${frappe.utils.escape_html(data.sales_invoice || '')}</b></p><p>${__('Payment Intent')}: <b>${frappe.utils.escape_html(data.payment_intent || '')}</b></p><p>${__('Payment Entry')}: <b>${frappe.utils.escape_html(data.payment_entry || '')}</b></p><p>${__('Terminal')}: <b>${frappe.utils.escape_html(data.terminal_id || '')}</b></p></div>`,
                                indicator: 'green'
                            });
                            frm.reload_doc();
                        }
                    });
                }
            });
            dialog.show();
        }, __('Payments'));
    }

    frm.add_custom_button(__('Refresh Payment Summary'), function() {
        frappe.call({
            method: 'payment_orchestrator.api.allocations.sync_reference_summary',
            args: { reference_doctype: frm.doctype, reference_name: frm.doc.name },
            callback() { frm.reload_doc(); }
        });
    }, __('Payments'));
};

['CRM Lead', 'Patient Encounter', 'Sales Order', 'Sales Invoice'].forEach((doctype) => {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            payment_orchestrator.get_settings_context((settings) => {
                payment_orchestrator.add_request_payment_button(frm, settings);
                if (settings.show_payment_summary_on_reference_doctypes && payment_orchestrator.is_doctype_enabled(frm, settings)) {
                    payment_orchestrator.render_dashboard(frm);
                }
            });
        }
    });
});
