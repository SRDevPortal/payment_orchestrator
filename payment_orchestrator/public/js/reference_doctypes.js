frappe.provide('payment_orchestrator');

payment_orchestrator.get_settings_context = function(callback) {
    frappe.call({
        method: 'payment_orchestrator.api.settings.get_settings_context',
        callback(r) {
            payment_orchestrator.settings = r.message || {};
            callback(payment_orchestrator.settings);
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

payment_orchestrator.is_saved_doc = function(frm) {
    const is_new = typeof frm.is_new === 'function' ? frm.is_new() : frm.is_new;
    return Boolean(frm.doc && frm.doc.name && !is_new);
};

payment_orchestrator.can_show_payment_actions = function(frm, settings) {
    if (!payment_orchestrator.is_saved_doc(frm)) return false;
    if (!settings.show_action_buttons || !payment_orchestrator.is_doctype_enabled(frm, settings)) return false;

    if (frm.doctype === 'Patient Encounter') {
        return frm.doc.sr_encounter_type === 'Order' && Number(frm.doc.docstatus || 0) === 0;
    }

    if (frm.doctype === 'Sales Invoice') {
        return Number(frm.doc.docstatus || 0) === 1 && parseFloat(frm.doc.outstanding_amount || 0) > 0;
    }

    if (frm.doctype === 'Sales Order') {
        return Number(frm.doc.docstatus || 0) < 2 && parseFloat(frm.doc.grand_total || frm.doc.base_grand_total || 0) > 0;
    }

    return true;
};

payment_orchestrator.is_patient_encounter_collectible = function(frm) {
    return frm.doctype === 'Patient Encounter'
        && frm.doc.sr_encounter_type === 'Order'
        && Number(frm.doc.docstatus || 0) === 0;
};

payment_orchestrator.is_sales_invoice_collectible = function(frm) {
    return frm.doctype === 'Sales Invoice'
        && Number(frm.doc.docstatus || 0) === 1
        && parseFloat(frm.doc.outstanding_amount || 0) > 0;
};

payment_orchestrator.is_sales_order_collectible = function(frm) {
    return frm.doctype === 'Sales Order'
        && Number(frm.doc.docstatus || 0) < 2
        && parseFloat(frm.doc.grand_total || frm.doc.base_grand_total || 0) > 0;
};

payment_orchestrator.is_crm_lead_collectible = function(frm) {
    return frm.doctype === 'CRM Lead';
};

payment_orchestrator.can_collect_payment = function(frm, settings) {
    if (!payment_orchestrator.can_show_payment_actions(frm, settings)) return false;
    return payment_orchestrator.is_patient_encounter_collectible(frm)
        || payment_orchestrator.is_sales_invoice_collectible(frm)
        || payment_orchestrator.is_sales_order_collectible(frm)
        || payment_orchestrator.is_crm_lead_collectible(frm);
};

payment_orchestrator.can_show_payment_link_action = function(frm, settings) {
    return payment_orchestrator.can_collect_payment(frm, settings);
};

payment_orchestrator.can_show_qr_code_action = function(frm, settings) {
    if (!payment_orchestrator.can_collect_payment(frm, settings)) return false;
    return ['Patient Encounter', 'Sales Order', 'Sales Invoice'].includes(frm.doctype);
};

payment_orchestrator.can_show_pinelabs_pos_action = function(frm, settings) {
    return Boolean(settings.enable_pinelabs_pos)
        && (
            payment_orchestrator.is_sales_invoice_collectible(frm)
            || payment_orchestrator.is_patient_encounter_collectible(frm)
        );
};

payment_orchestrator.can_show_pinelabs_pos_demo_action = function(frm, settings) {
    return Boolean(settings.enable_pinelabs_pos)
        && String(settings.pinelabs_pos_mode || 'Test') !== 'Live'
        && (
            payment_orchestrator.is_patient_encounter_collectible(frm)
            || payment_orchestrator.is_sales_invoice_collectible(frm)
        );
};

payment_orchestrator.can_show_payment_dashboard = function(frm, settings) {
    return payment_orchestrator.is_saved_doc(frm)
        && settings.show_payment_summary_on_reference_doctypes
        && payment_orchestrator.is_doctype_enabled(frm, settings);
};

payment_orchestrator.has_payment_summary_history = function(frm) {
    if (!frm.doc) return false;
    return Boolean(
        frm.doc.po_last_payment_intent
        || parseFloat(frm.doc.po_total_requested || 0) > 0
        || parseFloat(frm.doc.po_total_paid || 0) > 0
        || parseFloat(frm.doc.po_total_allocated || 0) > 0
        || parseFloat(frm.doc.po_total_unallocated || 0) > 0
    );
};

payment_orchestrator.can_show_refresh_payment_summary = function(frm, settings) {
    return payment_orchestrator.is_saved_doc(frm)
        && payment_orchestrator.is_doctype_enabled(frm, settings)
        && Boolean(frm.fields_dict.po_last_payment_intent || frm.fields_dict.po_payment_dashboard_html)
        && payment_orchestrator.has_payment_summary_history(frm);
};

payment_orchestrator.payment_summary_fields = [
    'po_payment_tab',
    'po_total_requested',
    'po_total_paid',
    'po_total_allocated',
    'po_total_unallocated',
    'po_last_payment_intent',
    'po_payment_dashboard_html',
];

payment_orchestrator.toggle_payment_summary_fields = function(frm, settings) {
    const visible = payment_orchestrator.is_doctype_enabled(frm, settings);
    payment_orchestrator.payment_summary_fields.forEach((fieldname) => {
        if (frm.fields_dict[fieldname]) {
            frm.toggle_display(fieldname, visible);
        }
    });
};

payment_orchestrator.get_pos_context = function(callback) {
    frappe.call({
        method: 'payment_orchestrator.api.pinelabs.get_pos_context',
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

payment_orchestrator.is_payment_failed = function(intent) {
    if (!intent) return false;
    const status = String(intent.status || '').toLowerCase();
    const provider_status = String(intent.pos_failure_reason || intent.payment_status || intent.pos_request_status || '').toLowerCase();
    return (
        ['cancelled', 'canceled', 'expired', 'failed'].includes(status) ||
        provider_status.includes('cancel') ||
        provider_status.includes('expired') ||
        provider_status.includes('failed') ||
        provider_status.includes('invalid') ||
        provider_status.includes('declined') ||
        provider_status.includes('error')
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
    if (watcher.failure_handler && frappe.realtime && frappe.realtime.off) {
        frappe.realtime.off('payment_orchestrator_payment_failed', watcher.failure_handler);
    }
    delete payment_orchestrator.payment_watchers[payment_intent];
};

payment_orchestrator.escape_html = function(value) {
    return frappe.utils.escape_html(String(value || ''));
};

payment_orchestrator.copy_text = function(value, message) {
    const text = String(value || '');
    if (!text) return;

    if (frappe.utils && frappe.utils.copy_to_clipboard) {
        frappe.utils.copy_to_clipboard(text);
        frappe.show_alert({ message: message || __('Copied'), indicator: 'green' }, 5);
        return;
    }

    navigator.clipboard.writeText(text).then(() => {
        frappe.show_alert({ message: message || __('Copied'), indicator: 'green' }, 5);
    });
};

payment_orchestrator.download_url = function(url, filename) {
    const download = function(object_url) {
        const link = document.createElement('a');
        link.href = object_url;
        link.download = filename || 'payment-qr-code.png';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    };

    fetch(url)
        .then((response) => {
            if (!response.ok) {
                throw new Error('Unable to download');
            }
            return response.blob();
        })
        .then((blob) => {
            const object_url = URL.createObjectURL(blob);
            download(object_url);
            setTimeout(() => URL.revokeObjectURL(object_url), 1000);
        })
        .catch(() => {
            window.open(url, '_blank');
            frappe.show_alert({
                message: __('QR opened in a new tab. Use browser save if download is blocked.'),
                indicator: 'orange'
            }, 8);
        });
};

payment_orchestrator.safe_external_url = function(value) {
    const url = String(value || '').trim();
    if (!url) return '';
    if (/^https?:\/\//i.test(url)) return url;
    return '';
};

payment_orchestrator.render_dashboard_intent = function(row) {
    const payment_link_url = payment_orchestrator.safe_external_url(row.payment_link_url);
    const qr_code_url = payment_orchestrator.safe_external_url(row.qr_code_url);
    return `
        <div style="padding:8px 0;border-bottom:1px solid #eee;">
            <div><b>${payment_orchestrator.escape_html(row.name)}</b> - ${payment_orchestrator.escape_html(row.status)}</div>
            <div style="font-size:12px;color:#666;">
                ${payment_orchestrator.escape_html(row.gateway || '')}
                ${payment_orchestrator.escape_html(row.payment_mode || '')}
                | ${payment_orchestrator.escape_html(row.request_type || '')}
                | Requested: ${payment_orchestrator.escape_html(row.amount_requested)}
                | Paid: ${payment_orchestrator.escape_html(row.amount_paid)}
                | Allocated: ${payment_orchestrator.escape_html(row.amount_allocated)}
            </div>
            ${payment_link_url ? `<div style="font-size:12px;"><a href="${payment_orchestrator.escape_html(payment_link_url)}" target="_blank" rel="noopener noreferrer">Open Payment Link</a></div>` : ''}
            ${qr_code_url ? `<div style="font-size:12px;"><a href="${payment_orchestrator.escape_html(qr_code_url)}" target="_blank" rel="noopener noreferrer">Open QR Code</a></div>` : ''}
        </div>
    `;
};

payment_orchestrator.payment_result_button = function(label, action, value, extra_attrs) {
    const attrs = [
        `data-po-action="${payment_orchestrator.escape_html(action)}"`,
        `data-po-value="${payment_orchestrator.escape_html(value)}"`,
        extra_attrs || '',
    ].join(' ');
    return `<button type="button" class="btn btn-xs btn-default" ${attrs}>${payment_orchestrator.escape_html(label)}</button>`;
};

payment_orchestrator.render_payment_link_result = function(data) {
    const url = payment_orchestrator.escape_html(data.payment_link_url || '');
    const show_message_preview = Boolean((payment_orchestrator.settings || {}).show_whatsapp_message_preview);
    return `
        <div class="po-payment-result" style="text-align:center;">
            <p><a href="${url}" target="_blank" rel="noopener noreferrer">${url}</a></p>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;justify-content:center;">
                ${payment_orchestrator.payment_result_button(__('Send WhatsApp'), 'whatsapp', data.payment_intent || '')}
                ${show_message_preview ? payment_orchestrator.payment_result_button(__('Show Message'), 'show_message', data.payment_intent || '') : ''}
                ${payment_orchestrator.payment_result_button(__('Copy Link'), 'copy', data.payment_link_url || '')}
                ${payment_orchestrator.payment_result_button(__('Open Link'), 'open', data.payment_link_url || '')}
            </div>
        </div>
    `;
};

payment_orchestrator.render_qr_result = function(data) {
    const url = payment_orchestrator.escape_html(data.qr_code_url || '');
    const filename = payment_orchestrator.escape_html(`payment-qr-${data.payment_intent || frappe.datetime.now_datetime()}.png`);
    const show_message_preview = Boolean((payment_orchestrator.settings || {}).show_whatsapp_message_preview);
    return `
        <div class="po-payment-result" style="text-align:center;">
            <div style="margin-top:12px;">
                <img src="${url}" style="max-width:260px;width:100%;height:auto;border:1px solid #e5e7eb;padding:8px;border-radius:6px;background:#fff;">
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px;justify-content:center;">
                ${payment_orchestrator.payment_result_button(__('Send WhatsApp'), 'whatsapp', data.payment_intent || '')}
                ${show_message_preview ? payment_orchestrator.payment_result_button(__('Show Message'), 'show_message', data.payment_intent || '') : ''}
                ${payment_orchestrator.payment_result_button(
                    __('Download QR Code'),
                    'download',
                    data.qr_code_url || '',
                    `data-po-filename="${filename}"`
                )}
            </div>
        </div>
    `;
};

payment_orchestrator.render_pos_result = function(data) {
    return `
        <div class="po-payment-result" style="text-align:center;">
            <p>${__('Payment Intent')}: <b>${frappe.utils.escape_html(data.payment_intent || '')}</b></p>
            <p>${__('Request Type')}: <b>${frappe.utils.escape_html(data.request_type || '')}</b></p>
            <p>${__('Method')}: <b>${frappe.utils.escape_html(data.pos_payment_method || '')}</b></p>
            <p>${__('POS Request')}: <b>${frappe.utils.escape_html(data.provider_pos_request_id || data.pos_request_status || '')}</b></p>
            <p>${__('Terminal')}: <b>${frappe.utils.escape_html(data.terminal_id || '')}</b></p>
            ${data.sales_invoice ? `<p>${__('Sales Invoice')}: <b>${frappe.utils.escape_html(data.sales_invoice || '')}</b></p>` : ''}
        </div>
    `;
};

payment_orchestrator.bind_payment_result_actions = function() {
    if (payment_orchestrator.payment_result_actions_bound) return;
    payment_orchestrator.payment_result_actions_bound = true;

    $(document).on('click', '[data-po-action]', function() {
        const $button = $(this);
        const action = $button.attr('data-po-action');
        const value = $button.attr('data-po-value');

        if (action === 'copy') {
            payment_orchestrator.copy_text(value, __('Copied'));
        } else if (action === 'open') {
            window.open(value, '_blank', 'noopener');
        } else if (action === 'download') {
            payment_orchestrator.download_url(value, $button.attr('data-po-filename'));
        } else if (action === 'whatsapp') {
            payment_orchestrator.send_payment_whatsapp(value);
        } else if (action === 'show_message') {
            payment_orchestrator.toggle_payment_whatsapp_message(value, $button);
        }
    });
};

payment_orchestrator.toggle_payment_whatsapp_message = function(payment_intent, $button) {
    const $container = $button.closest('.po-payment-result');
    const $preview = $container.find('.po-message-preview');
    if ($preview.length && $preview.is(':visible')) {
        $preview.slideUp(120);
        $button.text(__('Show Message'));
        return;
    }
    payment_orchestrator.show_payment_whatsapp_message(payment_intent, $container, $button);
};

payment_orchestrator.show_payment_whatsapp_message = function(payment_intent, $container, $button) {
    if (!payment_intent) {
        frappe.msgprint(__('Payment Intent is required to show message.'));
        return;
    }

    frappe.call({
        method: 'payment_orchestrator.api.whatsapp.get_payment_message_preview',
        args: { payment_intent },
        freeze: true,
        freeze_message: __('Preparing message...'),
        callback(r) {
            const data = r.message || {};
            if (data.message) {
                payment_orchestrator.render_message_preview($container, data.message);
                if ($button && $button.length) {
                    $button.text(__('Hide Message'));
                }
            }
        },
    });
};

payment_orchestrator.render_message_preview = function($container, message) {
    if (!$container || !$container.length) {
        payment_orchestrator.copy_text(message, __('Message copied'));
        return;
    }

    const escaped_message = payment_orchestrator.escape_html(message);
    let $preview = $container.find('.po-message-preview');
    if (!$preview.length) {
        $preview = $(`
            <div class="po-message-preview" style="display:none;margin:14px auto 0;max-width:520px;text-align:left;">
                <div style="font-size:12px;font-weight:600;margin-bottom:6px;">${__('WhatsApp Message')}</div>
                <pre class="po-message-preview-text" style="white-space:pre-wrap;background:#f8fafc;border:1px solid #e5e7eb;border-radius:6px;padding:10px;margin:0;max-height:220px;overflow:auto;font-size:13px;line-height:1.45;"></pre>
                <div style="display:flex;justify-content:flex-end;margin-top:8px;">
                    <button type="button" class="btn btn-xs btn-primary po-copy-preview-message">${__('Copy')}</button>
                </div>
            </div>
        `);
        $container.append($preview);
        $preview.on('click', '.po-copy-preview-message', function() {
            payment_orchestrator.copy_text($preview.find('.po-message-preview-text').text(), __('Message copied'));
        });
    }
    $preview.find('.po-message-preview-text').html(escaped_message);
    $preview.slideDown(120);
};

payment_orchestrator.send_payment_whatsapp = function(payment_intent, mobile_no) {
    if (!payment_intent) {
        frappe.msgprint(__('Payment Intent is required to send WhatsApp.'));
        return;
    }

    frappe.call({
        method: 'payment_orchestrator.api.whatsapp.send_payment_request',
        args: {
            payment_intent,
            mobile_no: mobile_no || '',
        },
        freeze: true,
        freeze_message: __('Sending WhatsApp...'),
        callback(r) {
            const data = r.message || {};
            if (data.needs_mobile) {
                payment_orchestrator.prompt_payment_whatsapp_mobile(payment_intent);
                return;
            }
            if (data.ok) {
                frappe.show_alert({
                    message: __('WhatsApp sent to {0}', [data.mobile_no || '']),
                    indicator: 'green',
                }, 8);
            }
        },
    });
};

payment_orchestrator.prompt_payment_whatsapp_mobile = function(payment_intent) {
    const dialog = new frappe.ui.Dialog({
        title: __('Send WhatsApp'),
        fields: [
            { label: __('Mobile Number'), fieldname: 'mobile_no', fieldtype: 'Data', reqd: 1 },
        ],
        primary_action_label: __('Send WhatsApp'),
        primary_action(values) {
            payment_orchestrator.hide_dialog(dialog);
            payment_orchestrator.send_payment_whatsapp(payment_intent, values.mobile_no);
        },
    });
    dialog.show();
};

payment_orchestrator.watch_payment_completion = function(payment_intent, options) {
    if (!payment_intent) return;
    const opts = options || {};
    const dialog = opts.dialog;
    const frm = opts.frm;
    const timeout_ms = opts.timeout_ms || 10 * 60 * 1000;
    const provider_poll_ms = opts.provider_poll_ms || 15 * 1000;
    const started_at = Date.now();
    let last_provider_fetch = 0;

    payment_orchestrator.stop_payment_watcher(payment_intent);

    const watcher = { stopped: false };
    payment_orchestrator.payment_watchers[payment_intent] = watcher;

    const complete = function(data) {
        if (watcher.stopped) return;
        payment_orchestrator.stop_payment_watcher(payment_intent);

        payment_orchestrator.hide_payment_dialog(dialog);
        frappe.show_alert({
            message: __('Payment received and allocated'),
            indicator: 'green'
        }, 8);
        if (frm && frm.reload_doc) {
            frm.reload_doc();
        }
    };

    const fail = function(message) {
        if (watcher.stopped) return;
        payment_orchestrator.stop_payment_watcher(payment_intent);

        payment_orchestrator.hide_payment_dialog(dialog);
        frappe.show_alert({
            message: message || __('Payment was cancelled or failed on terminal'),
            indicator: 'red'
        }, 10);
        if (frm && frm.reload_doc) {
            frm.reload_doc();
        }
    };

    const poll = function() {
        if (watcher.stopped) return;
        if (Date.now() - started_at > timeout_ms) {
            fail(__('Payment status check timed out. Please open the Payment Intent to sync latest status.'));
            return;
        }
        frappe.call({
            method: 'payment_orchestrator.api.common.intents.get_payment_intent',
            args: { payment_intent },
            callback(r) {
                const intent = r.message || {};
                if (payment_orchestrator.is_payment_complete(intent)) {
                    complete(intent);
                    return;
                }
                if (payment_orchestrator.is_payment_failed(intent)) {
                    fail(intent.pos_failure_reason || intent.payment_status || intent.pos_request_status || intent.status);
                    return;
                }
                const now = Date.now();
                if (now - last_provider_fetch < provider_poll_ms) {
                    return;
                }
                last_provider_fetch = now;

                if (
                    intent.payment_mode === 'Payment Link'
                    && intent.provider_link_id
                    && ['Pine Labs', 'Razorpay'].includes(intent.gateway)
                ) {
                    frappe.call({
                        method: intent.gateway === 'Pine Labs'
                            ? 'payment_orchestrator.api.pinelabs.fetch_payment_link'
                            : 'payment_orchestrator.api.razorpay.fetch_payment_link',
                        args: { payment_intent },
                        callback(fetch_response) {
                            const result = (fetch_response.message || {}).result || {};
                            if (result.payment_intent || (fetch_response.message || {}).processed) {
                                poll();
                            }
                        },
                        error() {
                            // Keep the UI watcher alive; webhook/callback may still update the intent.
                        }
                    });
                } else if (
                    intent.payment_mode === 'QR Code'
                    && intent.provider_qr_id
                    && intent.gateway === 'Razorpay'
                ) {
                    frappe.call({
                        method: 'payment_orchestrator.api.razorpay.fetch_qr_code',
                        args: { payment_intent },
                        callback() {
                            poll();
                        },
                        error() {
                            // Keep the UI watcher alive; webhook/callback may still update the intent.
                        }
                    });
                } else if (
                    intent.payment_mode === 'POS'
                    && intent.provider_pos_request_id
                    && intent.gateway === 'Pine Labs'
                ) {
                    frappe.call({
                        method: 'payment_orchestrator.api.pinelabs.fetch_pos_payment_status',
                        args: { payment_intent },
                        callback(pos_response) {
                            const pos_result = pos_response.message || {};
                            if (pos_result.failed) {
                                fail(pos_result.failure_message);
                                return;
                            }
                            poll();
                        },
                        error() {
                            // Keep polling; the terminal may still complete the payment.
                        }
                    });
                }
            }
        });
    };

    watcher.realtime_handler = function(data) {
        if ((data || {}).payment_intent === payment_intent) {
            complete(data);
        }
    };
    watcher.failure_handler = function(data) {
        if ((data || {}).payment_intent === payment_intent) {
            fail((data || {}).message || __('Payment was cancelled or failed on terminal'));
        }
    };
    if (frappe.realtime && frappe.realtime.on) {
        frappe.realtime.on('payment_orchestrator_payment_completed', watcher.realtime_handler);
        frappe.realtime.on('payment_orchestrator_payment_failed', watcher.failure_handler);
    }

    watcher.interval = setInterval(poll, 3000);
    watcher.timeout = setTimeout(() => {
        frappe.call({
            method: 'payment_orchestrator.api.sync.expire_stale_unpaid_intents',
            args: { limit: 100 },
            always() {
                fail(__('POS payment request expired without successful payment.'));
            }
        });
    }, timeout_ms);
    setTimeout(poll, 1500);

    if (dialog && dialog.$wrapper) {
        dialog.$wrapper.on('hidden.bs.modal', () => payment_orchestrator.stop_payment_watcher(payment_intent));
    }
};

payment_orchestrator.hide_payment_dialog = function(dialog) {
    payment_orchestrator.blur_active_modal_element();
    if (dialog && dialog.hide) {
        dialog.hide();
    }
    if (frappe.msg_dialog && frappe.msg_dialog.hide) {
        frappe.msg_dialog.hide();
    }
    if (frappe.hide_msgprint) {
        frappe.hide_msgprint();
    }
};

payment_orchestrator.hide_dialog = function(dialog) {
    payment_orchestrator.blur_active_modal_element();
    if (dialog && dialog.hide) {
        dialog.hide();
    }
};

payment_orchestrator.blur_active_modal_element = function() {
    const active = document.activeElement;
    if (active && active.blur && $(active).closest('.modal').length) {
        active.blur();
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
                        ${intents.length ? intents.map(payment_orchestrator.render_dashboard_intent).join('') : '<div style="color:#666;">No payment intents yet.</div>'}
                    </div>
                </div>
            `;
            if (!frm.fields_dict.po_payment_dashboard_html) {
                const dashboard_wrapper = frm.dashboard && (frm.dashboard.wrapper || frm.dashboard.parent);
                if (dashboard_wrapper) {
                    $(dashboard_wrapper).find('.po-dashboard').closest('.form-dashboard-section').remove();
                }
                frm.dashboard.add_section(html, __('Payment Summary'));
            } else {
                frm.fields_dict.po_payment_dashboard_html.$wrapper.html(html);
            }
        }
    });
};

payment_orchestrator.add_request_payment_button = function(frm, settings) {
    if (!payment_orchestrator.can_collect_payment(frm, settings)) return;
    const payment_action_group = __('Payment Actions');

    if (settings.enable_razorpay_payment_link && payment_orchestrator.can_show_payment_link_action(frm, settings)) {
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
                    method: 'payment_orchestrator.api.razorpay.create_payment_link',
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
                        payment_orchestrator.hide_dialog(dialog);
                        if (data.payment_link_url) {
                            frappe.msgprint({
                                title: __('Payment Link Created'),
                                message: payment_orchestrator.render_payment_link_result(data),
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
        }, payment_action_group);
    }

    if (settings.enable_razorpay_qr_code && payment_orchestrator.can_show_qr_code_action(frm, settings)) {
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
                        method: 'payment_orchestrator.api.razorpay.create_qr_code',
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
                            payment_orchestrator.hide_dialog(dialog);
                            if (data.qr_code_url) {
                                frappe.msgprint({
                                    title: __('QR Code Created'),
                                    message: payment_orchestrator.render_qr_result(data),
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
        }, payment_action_group);
    }

    if (settings.enable_pinelabs_payment_link && payment_orchestrator.can_show_payment_link_action(frm, settings)) {
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
                        method: 'payment_orchestrator.api.pinelabs.create_payment_link',
                        args: {
                            reference_doctype: frm.doctype,
                            reference_name: frm.doc.name,
                            amount: values.amount,
                            request_type: values.request_type,
                            notes: values.notes,
                        },
                        freeze: true,
                        freeze_message: __('Generating Pine Labs payment link...'),
                        callback(r) {
                            const data = r.message || {};
                            payment_orchestrator.hide_dialog(dialog);
                            if (data.payment_link_url) {
                                frappe.msgprint({
                                    title: __('Payment Link Created'),
                                    message: payment_orchestrator.render_payment_link_result(data),
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
        }, payment_action_group);
    }

    if (payment_orchestrator.can_show_pinelabs_pos_action(frm, settings)) {
        frm.add_custom_button(__('Pine Labs POS'), function() {
            const default_amount = frm.doc.outstanding_amount || frm.doc.grand_total || frm.doc.base_grand_total || frm.doc.paid_amount || 0;
            const request_type_options = frm.doctype === 'Sales Invoice' ? 'Against Invoice' : 'Advance\nAgainst Invoice';
            const default_request_type = frm.doctype === 'Sales Invoice' ? 'Against Invoice' : 'Advance';
            const dialog = new frappe.ui.Dialog({
                title: __('Pine Labs POS Payment'),
                fields: [
                    { label: __('Amount'), fieldname: 'amount', fieldtype: 'Currency', reqd: 1, default: default_amount },
                    {
                        label: __('Request Type'),
                        fieldname: 'request_type',
                        fieldtype: 'Select',
                        options: request_type_options,
                        default: default_request_type,
                        reqd: 1,
                        read_only: frm.doctype === 'Sales Invoice' ? 1 : 0,
                    },
                    {
                        label: __('Payment Method'),
                        fieldname: 'pos_payment_method',
                        fieldtype: 'Select',
                        options: 'All Modes\nCard\nUPI / QR',
                        default: 'All Modes',
                        reqd: 1,
                    },
                    { label: __('Notes'), fieldname: 'notes', fieldtype: 'Small Text' }
                ],
                primary_action_label: __('Send to POS'),
                primary_action(values) {
                    frappe.call({
                        method: 'payment_orchestrator.api.pinelabs.request_pos_payment_from_reference',
                        args: {
                            reference_doctype: frm.doctype,
                            reference_name: frm.doc.name,
                            amount: values.amount,
                            request_type: values.request_type || default_request_type,
                            pos_payment_method: values.pos_payment_method || 'All Modes',
                            notes: values.notes,
                        },
                        freeze: true,
                        freeze_message: __('Sending payment request to POS machine...'),
                        callback(r) {
                            const data = r.message || {};
                            payment_orchestrator.hide_dialog(dialog);
                            frappe.msgprint({
                                title: __('POS Payment Requested'),
                                message: payment_orchestrator.render_pos_result(data),
                                indicator: 'green'
                            });
                            const pos_timeout_minutes = Number(data.auto_cancel_duration || 5) + 1;
                            payment_orchestrator.watch_payment_completion(data.payment_intent, {
                                frm,
                                dialog: frappe.msg_dialog,
                                provider_poll_ms: 1500,
                                timeout_ms: pos_timeout_minutes * 60 * 1000,
                            });
                        }
                    });
                }
            });
            dialog.show();
        }, payment_action_group);
    }

    if (payment_orchestrator.can_show_pinelabs_pos_demo_action(frm, settings)) {
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
                        method: 'payment_orchestrator.api.pinelabs.mock_pos_payment',
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
                            payment_orchestrator.hide_dialog(dialog);
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
        }, payment_action_group);
    }
};

payment_orchestrator.add_refresh_payment_summary_button = function(frm, settings) {
    if (!payment_orchestrator.can_show_refresh_payment_summary(frm, settings)) return;
    frm.add_custom_button(__('Refresh Payment Summary'), function() {
        frappe.call({
            method: 'payment_orchestrator.api.allocations.sync_reference_summary',
            args: { reference_doctype: frm.doctype, reference_name: frm.doc.name },
            callback() { frm.reload_doc(); }
        });
    }, __('Payment Actions'));
};

if (!payment_orchestrator.reference_doctype_handlers_bound) {
    payment_orchestrator.reference_doctype_handlers_bound = true;
    payment_orchestrator.bind_payment_result_actions();

    ['CRM Lead', 'Patient Encounter', 'Sales Order', 'Sales Invoice'].forEach((doctype) => {
        frappe.ui.form.on(doctype, {
            refresh(frm) {
                payment_orchestrator.get_settings_context((settings) => {
                    payment_orchestrator.toggle_payment_summary_fields(frm, settings);
                    payment_orchestrator.add_request_payment_button(frm, settings);
                    payment_orchestrator.add_refresh_payment_summary_button(frm, settings);
                    if (payment_orchestrator.can_show_payment_dashboard(frm, settings)) {
                        payment_orchestrator.render_dashboard(frm);
                    }
                });
            }
        });
    });
}
