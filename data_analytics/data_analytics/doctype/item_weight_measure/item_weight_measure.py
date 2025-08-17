# Copyright (c) 2025, rayan aouf and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from datetime import date, timedelta
from frappe.utils import getdate, cint


class ItemWeightMeasure(Document):
	pass


@frappe.whitelist()
def generate_item_best_month(
    company: str,
    warehouse: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
):
    """
    Compute, for each item, the month (YYYY-MM) with the highest sold quantity.
    Args:
      company   (str)  : required
      warehouse (str?) : optional
      from_date (str?) : 'YYYY-MM-DD' (defaults to ~12 months ago, first day)
      to_date   (str?) : 'YYYY-MM-DD' (defaults to today)
      write_back(int)  : if truthy, write results into Single 'Item Weight Measure'
    Returns: dict { summary, results }
    """

    company = (company or "").strip()
    if not company:
        frappe.throw("Please provide a Company.")

    warehouse = (warehouse or "").strip()
    if not warehouse:
        frappe.throw("Please provide a Warehouse.")

	

    # Date range defaults
    today = date.today()
    default_from = (today.replace(day=1) - timedelta(days=365))
    from_date = getdate(from_date) if from_date else default_from
    to_date = getdate(to_date) if to_date else today

    # Build WHERE + params
    conditions = [
        "si.docstatus = 1",
        "si.company = %(company)s",
        "si.posting_date BETWEEN %(from)s AND %(to)s",
		"sii.warehouse = %(wh)s"
    ]
    params = {"company": company, "from": str(from_date), "to": str(to_date), "wh": warehouse}
 


    where_sql = " AND ".join(conditions)

    # One-shot SQL: aggregate per item/month, rank by qty desc (tie-break by most recent), keep rn=1
    sql = f"""
        WITH monthly AS (
            SELECT
                sii.item_code                               AS item_code,
                DATE_FORMAT(si.posting_date, '%%Y-%%m')      AS ym,
                YEAR(si.posting_date)                        AS y,
                MONTH(si.posting_date)                       AS m,
                SUM(sii.qty)                                 AS total_qty
            FROM `tabSales Invoice Item` sii
            JOIN `tabSales Invoice` si ON si.name = sii.parent
            WHERE {where_sql}
            GROUP BY sii.item_code, ym, y, m
        ),
        ranked AS (
            SELECT
                item_code, ym, y, m, total_qty,
                ROW_NUMBER() OVER (
                    PARTITION BY item_code
                    ORDER BY total_qty DESC, y DESC, m DESC
                ) AS rn
            FROM monthly
        )
        SELECT item_code, ym, y, m, total_qty
        FROM ranked
        WHERE rn = 1
        ORDER BY item_code
    """

    rows = frappe.db.sql(sql, params, as_dict=True)  # [{item_code, ym, y, m, total_qty}...]

    summary = {
        "items_with_best_month": len(rows),
        "date_range": f"{from_date} → {to_date}",
        "company": company,
        "warehouse": warehouse or None,
    }

    # Also return the rows so the client can render without reloading, if desired
    return {"summary": summary, "results": rows}