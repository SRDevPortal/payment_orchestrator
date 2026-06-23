frappe.ui.form.on('Payment Orchestrator Settings', {
    refresh(frm) {
        payment_orchestrator_settings_setup(frm);
    },
    show_advanced_settings(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_razorpay(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_razorpay_payment_link(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_razorpay_qr_code(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_razorpay_pos(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_razorpay_webhook_processing(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_pinelabs(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_pinelabs_pos(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_pinelabs_payment_link(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
    enable_pinelabs_postback_processing(frm) {
        payment_orchestrator_settings_apply_visibility(frm);
    },
});

function payment_orchestrator_settings_setup(frm) {
    payment_orchestrator_settings_apply_visibility(frm);
    payment_orchestrator_settings_disable_credential_autofill(frm);
    payment_orchestrator_settings_add_actions(frm);
}

function payment_orchestrator_settings_add_actions(frm) {
    frm.add_custom_button(__('Test Razorpay'), () => {
        frappe.call({
            method: 'payment_orchestrator.api.settings.test_provider_connection',
            freeze: true,
            freeze_message: __('Testing Razorpay connection...'),
            callback(r) {
                const data = r.message || {};
                frappe.msgprint({
                    title: __('Razorpay Connection'),
                    message: `${frappe.utils.escape_html(data.message || __('Connection test complete.'))}<br>${frappe.utils.escape_html(data.webhook_url || '')}`,
                    indicator: 'green'
                });
            }
        });
    });

    frm.add_custom_button(__('Copy Razorpay Webhook'), () => {
        frappe.call({
            method: 'payment_orchestrator.api.settings.get_settings_context',
            callback(r) {
                const url = (r.message || {}).webhook_url || '';
                if (!url) {
                    frappe.msgprint(__('Webhook URL is not available.'));
                    return;
                }
                frappe.utils.copy_to_clipboard(url);
                frappe.show_alert({ message: __('Webhook URL copied'), indicator: 'green' });
            }
        });
    });
}

function payment_orchestrator_settings_apply_visibility(frm) {
    const advanced = Boolean(frm.doc.show_advanced_settings);
    const razorpay = Boolean(frm.doc.enable_razorpay);
    const razorpay_link = razorpay && Boolean(frm.doc.enable_razorpay_payment_link);
    const razorpay_qr = razorpay && Boolean(frm.doc.enable_razorpay_qr_code);
    const razorpay_pos = razorpay && Boolean(frm.doc.enable_razorpay_pos);
    const razorpay_webhook = razorpay && Boolean(frm.doc.enable_razorpay_webhook_processing);
    const pinelabs = Boolean(frm.doc.enable_pinelabs);
    const pinelabs_pos = pinelabs && Boolean(frm.doc.enable_pinelabs_pos);
    const pinelabs_link = pinelabs && Boolean(frm.doc.enable_pinelabs_payment_link);

    const advanced_fields = [
        'section_feature_flags',
        'enable_refunds',
        'auto_allocate_encounter_advances',
        'auto_allocate_sales_order_advances',
        'auto_bind_invoice_payments',
        'pos_timeout_seconds',
        'section_behavior',
        'allow_overpayment',
        'create_unallocated_credit_for_excess',
        'auto_mark_reference_paid_when_fully_allocated',
        'column_break_behavior_1',
        'default_advance_account',
        'default_receivable_account',
        'default_cost_center',
        'section_ui',
        'section_security',
        'store_full_webhook_payload',
        'enable_duplicate_webhook_guard',
        'section_notes',
        'internal_notes',
    ];

    advanced_fields.forEach((fieldname) => frm.toggle_display(fieldname, advanced));

    [
        'razorpay_payment_link_sb',
        'enable_razorpay_payment_link',
        'razorpay_qr_code_sb',
        'enable_razorpay_qr_code',
        'razorpay_pos_sb',
        'enable_razorpay_pos',
        'razorpay_webhook_sb',
        'enable_razorpay_webhook_processing',
    ].forEach((fieldname) => frm.toggle_display(fieldname, razorpay));

    frm.toggle_display('razorpay_payment_link_mode', razorpay_link);
    frm.toggle_display('razorpay_qr_code_mode', razorpay_qr);
    [
        'razorpay_test_key_id',
        'razorpay_test_key_secret',
        'razorpay_live_key_id',
        'razorpay_live_key_secret',
    ].forEach((fieldname) => {
        frm.toggle_display(fieldname, razorpay_link || razorpay_qr || razorpay_pos);
    });
    ['key_id', 'key_secret'].forEach((fieldname) => frm.toggle_display(fieldname, false));
    frm.toggle_display('api_base_url', (razorpay_link || razorpay_qr || razorpay_pos) && advanced);
    frm.toggle_display('razorpay_pos_mode', razorpay_pos);
    frm.toggle_display('webhook_secret', razorpay_webhook);

    [
        'pinelabs_payment_link_sb',
        'enable_pinelabs_payment_link',
        'pinelabs_pos_sb',
        'enable_pinelabs_pos',
        'pinelabs_postback_sb',
        'enable_pinelabs_postback_processing',
    ].forEach((fieldname) => frm.toggle_display(fieldname, pinelabs));

    [
        'pinelabs_merchant_id',
        'pinelabs_security_token',
        'pinelabs_store_id',
        'pinelabs_client_id',
        'pinelabs_user_id',
        'pinelabs_allowed_payment_mode',
        'pinelabs_auto_cancel_duration',
        'default_pos_device_id',
        'pos_mode_of_payment',
        'pinelabs_pos_mode',
    ].forEach((fieldname) => frm.toggle_display(fieldname, pinelabs_pos));

    [
        'pinelabs_base_url',
        'pinelabs_upload_path',
        'pinelabs_status_path',
        'pinelabs_cancel_path',
        'pos_timeout_seconds',
    ].forEach((fieldname) => frm.toggle_display(fieldname, pinelabs_pos && advanced));

    [
        'pinelabs_online_client_id',
        'pinelabs_online_client_secret',
        'pinelabs_payment_link_callback_url',
        'pinelabs_payment_link_failure_callback_url',
        'pinelabs_payment_link_mode',
    ].forEach((fieldname) => frm.toggle_display(fieldname, pinelabs_link));

    [
        'pinelabs_online_base_url',
        'pinelabs_online_auth_path',
        'pinelabs_payment_link_path',
        'pinelabs_payment_link_allowed_methods',
    ].forEach((fieldname) => frm.toggle_display(fieldname, pinelabs_link && advanced));

    frm.toggle_display('pinelabs_postback_sb', pinelabs);
    frm.toggle_display('enable_pinelabs_postback_processing', pinelabs);

    payment_orchestrator_settings_disable_credential_autofill(frm);
}

function payment_orchestrator_settings_disable_credential_autofill(frm) {
    const credential_fields = [
        'key_id',
        'key_secret',
        'razorpay_test_key_id',
        'razorpay_test_key_secret',
        'razorpay_live_key_id',
        'razorpay_live_key_secret',
        'webhook_secret',
        'pinelabs_online_client_id',
        'pinelabs_online_client_secret',
        'pinelabs_merchant_id',
        'pinelabs_security_token',
        'pinelabs_store_id',
        'pinelabs_client_id',
        'pinelabs_user_id',
    ];

    credential_fields.forEach((fieldname) => {
        const field = frm.fields_dict[fieldname];
        if (!field || !field.$wrapper) {
            return;
        }

        const input = field.$input || field.$wrapper.find('input');
        if (!input || !input.length) {
            return;
        }

        input.attr({
            autocomplete: 'new-password',
            autocorrect: 'off',
            autocapitalize: 'off',
            spellcheck: 'false',
            'data-lpignore': 'true',
            'data-1p-ignore': 'true',
            'data-bwignore': 'true',
            'data-form-type': 'other',
        });
    });
}
