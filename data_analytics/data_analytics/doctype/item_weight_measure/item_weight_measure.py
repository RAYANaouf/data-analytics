# Copyright (c) 2025, rayan aouf and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date, timedelta


class ItemWeightMeasure(Document):
	pass



@frappe.whitelist()
def generate_item_best_month():
    """
    Compute, for each item, the month (YYYY-MM) with the highest sold quantity.
    Filters:
      - company (required)
      - warehouse (optional)
      - from_date/to_date (optional; defaults to last 12 months if empty)
    Writes rows into Single doctype's 'results' child table.
    Returns a summary dict.
    """
    # Load the single doc
    doc = frappe.get_single("Item Weight Measure")

    company = doc.company
    if not company:
        frappe.throw("Please select a Company first.")

    warehouse = (doc.warehouse or "").strip()

    # Date range defaults (last 12 months if none provided)
    today = date.today()
    default_from = (today.replace(day=1) - timedelta(days=365))  # approx 12 months back
    from_date = doc.from_date or default_from
    to_date = doc.to_date or today

    # Ensure strings
    from_date = str(from_date)
    to_date = str(to_date)

    # --- DATA SOURCE ---
    # We’ll use Sales Invoices (docstatus=1). If you prefer Delivery Notes, see comment below.
    # Join header for company/date; items table for item/qty/warehouse.
    # Group by item + month(YYYY-MM). Then we'll pick the max per item in Python.

    conditions = ["si.docstatus = 1", "si.company = %(company)s", "si.posting_date BETWEEN %(from)s AND %(to)s"]
    params = {"company": company, "from": from_date, "to": to_date}

    if warehouse:
        conditions.append("(sii.warehouse = %(wh)s)")
        params["wh"] = warehouse

    where_sql = " AND ".join(conditions)

    # NOTE: We aggregate by DATE_FORMAT to get YYYY-MM. Works on MariaDB/MySQL (default for Frappe).
    query = f"""
        SELECT
            sii.item_code                         AS item_code,
            DATE_FORMAT(si.posting_date, '%%Y-%%m') AS ym,
            YEAR(si.posting_date)                 AS y,
            MONTH(si.posting_date)                AS m,
            SUM(sii.qty)                          AS total_qty
        FROM `tabSales Invoice Item` sii
        INNER JOIN `tabSales Invoice` si ON si.name = sii.parent
        WHERE {where_sql}
        GROUP BY sii.item_code, ym, y, m
    """

    rows = frappe.db.sql(query, params, as_dict=True)

    # Pick best month per item (max qty)
    best_by_item = {}
    for r in rows:
        key = r["item_code"]
        if not key:
            continue
        current = best_by_item.get(key)
        if (current is None) or (r["total_qty"] > current["total_qty"]):
            best_by_item[key] = r

    # Clear existing table rows
    doc.set("results", [])

    # Fill results
    for item_code, rec in sorted(best_by_item.items(), key=lambda kv: kv[0] or ""):
        child = doc.append("results", {})
        child.item_code = item_code
        child.best_month = rec["ym"]
        child.best_qty = float(rec["total_qty"] or 0)
        child.year = int(rec["y"])
        child.month = int(rec["m"])

    doc.save(ignore_permissions=True)
    frappe.db.commit()

    return {
        "items_evaluated": len(set([r["item_code"] for r in rows if r.get("item_code")])),
        "items_with_best_month": len(best_by_item),
        "date_range": f"{from_date} → {to_date}",
        "company": company,
        "warehouse": warehouse or None,
    }

"""
If you prefer using Delivery Notes instead of Sales Invoices, swap the query to:

FROM `tabDelivery Note Item` dni
JOIN `tabDelivery Note` dn ON dn.name = dni.parent
WHERE dn.docstatus = 1 AND dn.company = %(company)s AND dn.posting_date BETWEEN %(from)s AND %(to)s
[+ optional warehouse filter on dni.warehouse]
GROUP BY dni.item_code, DATE_FORMAT(dn.posting_date, '%%Y-%%m'), YEAR(dn.posting_date), MONTH(dn.posting_date)

"""

