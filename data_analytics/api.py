
# data_analytics/api/brand_warehouse_summary.py
import frappe
from frappe import _

@frappe.whitelist()
def brand_warehouse_summary(companies=None, warehouses=None, include_groups=0, include_disabled=0, limit_brands=0):
    """
    Returns stock presence per ROOT brand per warehouse.

    Params (all optional):
      - companies: JSON array of company names; if empty, all companies
      - warehouses: JSON array of warehouse names; if empty, all warehouses in companies
      - include_groups: 1 to include is_group=1 nodes; default 0
      - include_disabled: 1 to include disabled warehouses; default 0
      - limit_brands: int, >0 to limit number of root brands returned (top by overall presence)

    Output:
    {
      "root_brands": ["RootA", "RootB", ...],
      "warehouses": [
        {"name":"WH-001","warehouse_name":"Main","company":"Company A","parent_warehouse":None,"is_group":0,"disabled":0,
         "brands":[{"root_brand":"RootA","qty":123.0,"item_count":17}, ...]
        }, ...
      ]
    }
    """
    import json
    # ---------- parse inputs ----------
    def parse_list(x):
        if not x: return []
        if isinstance(x, list): return x
        try:
            return json.loads(x)
        except Exception:
            return [x]

    companies = parse_list(companies)
    warehouses = parse_list(warehouses)
    include_groups = int(include_groups or 0)
    include_disabled = int(include_disabled or 0)
    limit_brands = int(limit_brands or 0)

    # ---------- load brands & compute root mapping ----------
    # Expect Brand has custom fields: father (Link to Brand), root (Check)
    brands = frappe.get_all("Brand", fields=["name", "father", "root"])
    bidx = {b["name"]: b for b in brands}

    # find all roots
    root_brands = {b["name"] for b in brands if int(b.get("root") or 0) == 1}
    if not root_brands:
        # if none flagged as root, treat brands with no father as roots
        root_brands = {b["name"] for b in brands if not b.get("father")}

    # map brand -> root brand by walking 'father'
    cache_root = {}
    def find_root(name, guard=0):
        if name in cache_root: return cache_root[name]
        if name not in bidx: 
            cache_root[name] = None
            return None
        if int(bidx[name].get("root") or 0) == 1:
            cache_root[name] = name
            return name
        if guard > 20:  # avoid cycles
            cache_root[name] = None
            return None
        parent = bidx[name].get("father")
        if not parent:
            cache_root[name] = name if name in root_brands else None
            return cache_root[name]
        res = find_root(parent, guard+1)
        cache_root[name] = res
        return res

    # ---------- build item_code -> root_brand ----------
    # Only items with a brand that resolves to a root
    items = frappe.get_all("Item", fields=["name", "brand"], filters={"disabled": 0})
    item_root = {}
    for it in items:
        rb = find_root(it.get("brand")) if it.get("brand") else None
        if rb:
            item_root[it["name"]] = rb

    if not item_root:
        return {"root_brands": sorted(root_brands), "warehouses": []}

    # ---------- select warehouses ----------
    wh_filters = {}
    if warehouses:
        wh_filters["name"] = ["in", warehouses]
    elif companies:
        wh_filters["company"] = ["in", companies]

    if not include_disabled:
        wh_filters["disabled"] = 0
    if not include_groups:
        wh_filters["is_group"] = 0

    wh_rows = frappe.get_all(
        "Warehouse",
        fields=["name","warehouse_name","company","parent_warehouse","is_group","disabled"],
        filters=wh_filters,
        order_by="company asc, warehouse_name asc",
        limit_page_length=10000
    )
    if not wh_rows:
        return {"root_brands": sorted(root_brands), "warehouses": []}

    wh_names = [w["name"] for w in wh_rows]

    # ---------- aggregate stock from Bin ----------
    # Bin is fast and already aggregated. We only need warehouse, item_code, actual_qty
    bins = frappe.get_all(
        "Bin",
        fields=["warehouse","item_code","actual_qty"],
        filters={"warehouse": ["in", wh_names]},
        limit_page_length=2000000  # large cap; server will paginate internally
    )

    # sum qty + count of items with stock > 0 by (warehouse, root_brand)
    from collections import defaultdict
    qty_map = defaultdict(float)
    count_set = defaultdict(set)

    for b in bins:
        it = b["item_code"]
        rb = item_root.get(it)
        if not rb:
            continue
        wh = b["warehouse"]
        qty = float(b.get("actual_qty") or 0)
        qty_map[(wh, rb)] += qty
        if qty > 0:
            count_set[(wh, rb)].add(it)

    # build brand order (optionally limited)
    brand_totals = defaultdict(float)
    for (wh, rb), q in qty_map.items():
        brand_totals[rb] += q
    brands_order = sorted(root_brands, key=lambda r: (-brand_totals.get(r, 0), r))
    if limit_brands > 0:
        brands_order = brands_order[:limit_brands]

    # assemble result
    wh_index = {w["name"]: w for w in wh_rows}
    result_wh = []
    for w in wh_rows:
        entry = dict(w)
        # for UI simplicity: include *all* requested brands; qty=0 if none
        brands_payload = []
        for rb in brands_order:
            q = qty_map.get((w["name"], rb), 0.0)
            c = len(count_set.get((w["name"], rb), set()))
            brands_payload.append({"root_brand": rb, "qty": round(q, 6), "item_count": int(c)})
        entry["brands"] = brands_payload
        result_wh.append(entry)

    return {
        "root_brands": list(brands_order),
        "warehouses": result_wh
    }
