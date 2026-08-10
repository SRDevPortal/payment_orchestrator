(function patchPaymentReferenceListViews() {
    const referenceDoctypes = [
        'CRM Lead',
        'Patient Encounter',
        'Sales Order',
        'Sales Invoice',
    ];
    const paymentFields = [
        'po_payment_status',
        'po_total_requested',
        'po_total_paid',
        'po_total_allocated',
        'po_total_unallocated',
        'po_last_payment_intent',
    ];

    function paymentStatusBadge(value, doc) {
        const status = String(value || 'Not Requested').trim();
        const kind = paymentStatusKind(status);
        const label = frappe.utils.escape_html(__(status));
        const title = frappe.utils.escape_html(paymentStatusTitle(doc));
        const badge = `<span class="po-list-status po-list-status-${kind}">${label}</span>`;
        const paymentIntent = String(doc.po_last_payment_intent || '').trim();

        if (!paymentIntent) {
            return `<span title="${title}">${badge}</span>`;
        }

		const href = `/desk/payment-intent/${encodeURIComponent(paymentIntent)}`;
        return `<a class="po-list-status-link" href="${href}" title="${title}">${badge}</a>`;
    }

    function paymentStatusKind(value) {
        const status = String(value || '').toLowerCase();
        if (status === 'allocated' || status === 'payment received') return 'success';
        if (status === 'partially allocated' || status === 'partially received') return 'info';
        if (status === 'awaiting payment') return 'pending';
        if (status === 'payment failed') return 'danger';
        if (status === 'expired') return 'warning';
        if (status.includes('refund')) return 'refund';
        return 'neutral';
    }

    function paymentStatusTitle(doc) {
        const currency = frappe.defaults.get_default('currency');
        const amount = (value) => format_currency(Number(value || 0), currency);
        return [
            __('Requested: {0}', [amount(doc.po_total_requested)]),
            __('Received: {0}', [amount(doc.po_total_paid)]),
            __('Allocated: {0}', [amount(doc.po_total_allocated)]),
            __('Unallocated: {0}', [amount(doc.po_total_unallocated)]),
        ].join(' | ');
    }

    referenceDoctypes.forEach((doctype) => {
        const existingSettings = frappe.listview_settings[doctype] || {};
        const existingFormatters = existingSettings.formatters || {};

        frappe.listview_settings[doctype] = {
            ...existingSettings,
            add_fields: Array.from(new Set([
                ...(existingSettings.add_fields || []),
                ...paymentFields,
            ])),
            formatters: {
                ...existingFormatters,
                po_payment_status(value, df, doc) {
                    return paymentStatusBadge(value, doc);
                },
            },
        };
    });
})();
