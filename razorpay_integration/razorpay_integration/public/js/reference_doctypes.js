frappe.provide('razorpay_integration');

razorpay_integration.get_pos_context = function(callback) {
    frappe.call({
        method: 'razorpay_integration.api.pos.get_pos_context',
        callback(r) {
            callback(r.message || {});
        }
    });
};

razorpay_integration.render_dashboard = function(frm) {
    frappe.call({
        method: 'razorpay_integration.api.dashboard.get_reference_dashboard',
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
                        ${intents.length ? intents.map(row => `<div style="padding:8px 0;border-bottom:1px solid #eee;"><div><b>${row.name}</b> — ${row.status}</div><div style="font-size:12px;color:#666;">${row.request_type} | Requested: ${row.amount_requested} | Paid: ${row.amount_paid} | Allocated: ${row.amount_allocated}</div>${row.payment_link_url ? `<div style="font-size:12px;"><a href="${row.payment_link_url}" target="_blank">Open Payment Link</a></div>` : ''}</div>`).join('') : '<div style="color:#666;">No payment intents yet.</div>'}
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

razorpay_integration.add_request_payment_button = function(frm) {
    if (frm.is_new && !frm.doc.name) return;

    frm.add_custom_button(__('Request Payment'), function() {
        const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
        const dialog = new frappe.ui.Dialog({
            title: __('Request Payment'),
            fields: [
                { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                { label: __('Request Type'), fieldname: 'request_type', fieldtype: 'Select', options: 'Advance\nAgainst Invoice', default: frm.doctype === 'Sales Invoice' ? 'Against Invoice' : 'Advance' },
                { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
            ],
            primary_action_label: __('Generate Payment Link'),
            primary_action(values) {
                frappe.call({
                    method: 'razorpay_integration.api.intents.create_payment_intent',
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
                        }
                        frm.reload_doc();
                    }
                });
            }
        });
        dialog.show();
    }, __('Payments'));

    if (frm.doctype === 'Sales Invoice' && frm.doc.docstatus === 1) {
        frm.add_custom_button(__('Request Payment on POS'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || 0;
            const dialog = new frappe.ui.Dialog({
                title: __('Request Payment on POS'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
                ],
                primary_action_label: __('Send to POS'),
                primary_action(values) {
                    frappe.call({
                        method: 'razorpay_integration.api.pos.request_pos_payment',
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

    if (['Patient Encounter', 'Sales Invoice'].includes(frm.doctype)) {
        frm.add_custom_button(__('Request Payment on POS (Demo)'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
            const dialog = new frappe.ui.Dialog({
                title: __('Request Payment on POS (Demo)'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text', default: 'Demo POS payment' }
                ],
                primary_action_label: __('Mock Paid on POS'),
                primary_action(values) {
                    frappe.call({
                        method: 'razorpay_integration.api.pos.mock_pos_payment',
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
            method: 'razorpay_integration.api.allocations.sync_reference_summary',
            args: { reference_doctype: frm.doctype, reference_name: frm.doc.name },
            callback() { frm.reload_doc(); }
        });
    }, __('Payments'));
};

['Lead', 'Patient Encounter', 'Sales Order', 'Sales Invoice'].forEach((doctype) => {
    frappe.ui.form.on(doctype, {
        refresh(frm) {
            razorpay_integration.add_request_payment_button(frm);
            razorpay_integration.render_dashboard(frm);
        }
    });
});
