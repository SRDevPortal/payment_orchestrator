import frappe


def execute():
    if not frappe.db.table_exists("Payment Provider Event") or not frappe.db.has_column(
        "Payment Provider Event", "duplicate_guard_key"
    ):
        return

    duplicate_keys = frappe.db.sql(
        """
        select duplicate_guard_key
        from `tabPayment Provider Event`
        where coalesce(duplicate_guard_key, '') != ''
        group by duplicate_guard_key
        having count(*) > 1
        """,
        pluck=True,
    )

    for guard_key in duplicate_keys:
        duplicate_names = frappe.get_all(
            "Payment Provider Event",
            filters={"duplicate_guard_key": guard_key},
            pluck="name",
            order_by="creation asc, name asc",
        )[1:]
        for event_name in duplicate_names:
            frappe.db.set_value(
                "Payment Provider Event",
                event_name,
                "duplicate_guard_key",
                None,
                update_modified=False,
            )
