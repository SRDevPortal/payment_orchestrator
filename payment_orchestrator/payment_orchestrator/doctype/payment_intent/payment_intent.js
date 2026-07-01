frappe.ui.form.on('Payment Intent', {
    refresh(frm) {
        add_admin_correction_button(frm);

        const locked_statuses = [
            'Paid',
            'Partially Allocated',
            'Allocated',
            'Refunded',
            'Cancelled',
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
