frappe.listview_settings['Payment Intent'] = {
    add_fields: [
        'status',
        'gateway',
        'payment_mode',
        'pos_payment_method',
        'provider_mode',
        'payment_status',
        'pos_request_status',
        'pos_failure_reason',
        'amount_requested',
        'amount_paid',
        'amount_allocated',
        'amount_unallocated',
    ],

    get_indicator(doc) {
        const status = String(doc.status || '').toLowerCase();
        const provider_status = String(doc.pos_failure_reason || doc.payment_status || doc.pos_request_status || '').toLowerCase();

        if (
            provider_status.includes('invalid') ||
            provider_status.includes('failed') ||
            provider_status.includes('error') ||
            provider_status.includes('declined') ||
            status === 'cancelled'
        ) {
            return [__(doc.status || 'Failed'), 'red', 'status,=,' + (doc.status || 'Cancelled')];
        }

        if (status === 'allocated' || status === 'paid') {
            return [__(doc.status), 'green', 'status,=,' + doc.status];
        }

        if (status === 'partially allocated' || status === 'partially paid') {
            return [__(doc.status), 'blue', 'status,=,' + doc.status];
        }

        if (status === 'expired') {
            return [__('Expired'), 'orange', 'status,=,Expired'];
        }

        if (provider_status.includes('uploaded') || status === 'requested') {
            return [__('Pending'), 'yellow', 'status,=,Requested'];
        }

        return [__(doc.status || 'Draft'), 'gray', 'status,=,' + (doc.status || 'Draft')];
    },

    formatters: {
        gateway(value, df, doc) {
            if (!value) return '';
            return `<span class="po-list-gateway po-list-gateway-${frappe.scrub(value)}">${frappe.utils.escape_html(value)}</span>`;
        },

        payment_status(value, df, doc) {
            const status = doc.pos_failure_reason || value || doc.pos_request_status || '';
            if (!status) return '';
            const kind = payment_intent_list_status_kind(status);
            return `<span class="po-list-status po-list-status-${kind}">${frappe.utils.escape_html(status)}</span>`;
        },

        amount_paid(value, df, doc) {
            const paid = Number(value || 0);
            const requested = Number(doc.amount_requested || 0);
            const html = frappe.format(value, df, doc);
            if (paid > 0 && requested > 0 && paid >= requested) {
                return `<span class="text-success">${html}</span>`;
            }
            return html;
        },
    },
};

function payment_intent_list_status_kind(value) {
    const status = String(value || '').toLowerCase();
    if (status.includes('invalid') || status.includes('failed') || status.includes('error') || status.includes('declined')) {
        return 'danger';
    }
    if (status.includes('approved') || status.includes('captured') || status === 'paid' || status === 'processed') {
        return 'success';
    }
    if (status.includes('uploaded') || status.includes('pending') || status.includes('requested')) {
        return 'pending';
    }
    if (status.includes('expired') || status.includes('closed')) {
        return 'warning';
    }
    return 'neutral';
}
