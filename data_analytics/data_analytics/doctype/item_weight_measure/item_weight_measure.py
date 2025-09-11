# Copyright (c) 2025, rayan aouf and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date, timedelta
from frappe.utils import getdate, cint


class ItemWeightMeasure(Document):
	pass


import frappe
from datetime import date, timedelta
from frappe.utils import getdate

@frappe.whitelist()
def generate_item_best_month(
    company: str,
    warehouse: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    """
    For each item in (company, warehouse, date-range):
      1) find the month with the highest sold qty (best_sell) from Sales Invoices
      2) read current on-hand qty in that warehouse (on_stock) from Bin
      3) compute need / overload
    Returns: { summary, results }
    """

    company = (company or "").strip()
    if not company:
        frappe.throw("Please provide a Company.")

    warehouse = (warehouse or "").strip()
    if not warehouse:
        frappe.throw("Please provide a Warehouse.")

    # Dates (defaults ~last 12 months)
    today = date.today()
    default_from = (today.replace(day=1) - timedelta(days=365))
    from_date = getdate(from_date) if from_date else default_from
    to_date = getdate(to_date) if to_date else today

    # Build WHERE + params
    conditions = [
        "si.docstatus = 1",
        "si.company = %(company)s",
        "si.posting_date BETWEEN %(from)s AND %(to)s",
        "sii.warehouse = %(wh)s",
        # Optional: ignore returns; uncomment next line if you don't want negative months
        # "IFNULL(si.is_return, 0) = 0",
    ]
    params = {"company": company, "from": str(from_date), "to": str(to_date), "wh": warehouse}
    where_sql = " AND ".join(conditions)

    # Best month per item (window function)
    best_sql = f"""
        WITH monthly AS (
            SELECT
                sii.item_code                          AS item_code,
                YEAR(si.posting_date)                  AS y,
                MONTH(si.posting_date)                 AS m,
                SUM(sii.qty)                           AS total_qty
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE {where_sql}
            GROUP BY sii.item_code, y, m
        ),
        ranked AS (
            SELECT
                item_code, y, m, total_qty,
                ROW_NUMBER() OVER (
                    PARTITION BY item_code
                    ORDER BY total_qty DESC, y DESC, m DESC
                ) AS rn
            FROM monthly
        )
        SELECT item_code, y, m, total_qty
        FROM ranked
        WHERE rn = 1
        ORDER BY item_code
    """
    #ranked section is for assign number for each record using the ROW_NUMBER() OVER function and then we select the first one witch is the best month.
    best_rows = frappe.db.sql(best_sql, params, as_dict=True)  # [{item_code,y,m,total_qty}]

    # Gather on-hand stock for those items in this warehouse
    item_codes = [r["item_code"] for r in best_rows if r.get("item_code")]
    bins = {}
    if item_codes:
        placeholders = ", ".join(["%s"] * len(item_codes))
        bin_sql = f"""
            SELECT item_code, COALESCE(actual_qty, 0) AS actual_qty
            FROM `tabBin`
            WHERE warehouse = %s AND item_code IN ({placeholders})
        """
        for b in frappe.db.sql(bin_sql, [warehouse, *item_codes], as_dict=True):
            bins[b["item_code"]] = float(b["actual_qty"] or 0)

    # Build final rows in the shape you asked for
    results = []
    for r in best_rows:
        item = r["item_code"]
        y, m = int(r["y"]), int(r["m"])
        best_sell = float(r["total_qty"] or 0)
        on_stock = float(bins.get(item, 0.0))
        need = max(best_sell - on_stock, 0.0)
        overload = max(on_stock - best_sell, 0.0)

        results.append({
            "item": item,
            "date": f"{y:04d}-{m:02d}-01",  # first day of best month (Date field friendly)
            "best_sell": best_sell,
            "on_stock": on_stock,
            "need": need,
            "overload": overload,
        })

    summary = {
        "items_with_best_month": len(results),
        "date_range": f"{from_date} → {to_date}",
        "company": company,
        "warehouse": warehouse,
    }
    return {"summary": summary, "results": results}
