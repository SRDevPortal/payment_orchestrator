import frappe
from frappe.model.document import Document


FINAL_STATUSES = {
    "Paid",
    "Partially Allocated",
    "Allocated",
    "Partially Refunded",
    "Refunded",
    "Cancelled",
    "Expired",
}


def is_payment_intent_system_update():
    return bool(getattr(frappe.flags, "payment_orchestrator_system_update", False))


class PaymentIntent(Document):
    def validate(self):
        self._protect_finalized_intent()

    def before_delete(self):
        frappe.throw("Payment Intent records cannot be deleted. Cancel or refund the payment instead.")

    def _protect_finalized_intent(self):
        if self.is_new() or is_payment_intent_system_update():
            return

        before_save = self.get_doc_before_save()
        if not before_save:
            return

        old_status = before_save.get("status")
        new_status = self.get("status")

        if old_status in FINAL_STATUSES:
            frappe.throw(
                "This Payment Intent is finalized and cannot be edited manually. "
                "Use Payment Orchestrator sync or refund/correction flow."
            )

        if new_status in FINAL_STATUSES and old_status != new_status:
            frappe.throw(
                "Payment Intent cannot be manually moved to a finalized payment status. "
                "Let the payment provider webhook/sync update it."
            )
