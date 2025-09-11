import json
import frappe
from collections import defaultdict

@frappe.whitelist()
def brand_warehouse_summary(companies=None, warehouses=None, include_groups=0, include_disabled=0, limit_brands=0):
    """
    Robust: auto-detect Brand custom fields for root/father, aggregate Bin by root brand per warehouse.

    URL (server script): /api/method/brand_warehouse_summary
    URL (custom app):    /api/method/data_analytics.api.brand_warehouse_summary
    """

    # ---------- helpers ----------
    def parse_list(x):
        if not x:
            return []
        if isinstance(x, list):
            return x
        try:
            return json.loads(x)
        except Exception:
            return [x]

    def bool_int(x):
        return 1 if str(x).strip() in ("1", "True", "true", "YES", "yes") else 0

    companies        = parse_list(companies)
    warehouses       = parse_list(warehouses)
    include_groups   = bool_int(include_groups)
    include_disabled = bool_int(include_disabled)
    limit_brands     = int(limit_brands or 0)

    # ---------- detect Brand custom fields ----------
    meta = frappe.get_meta("Brand")
    brand_fields = {f.fieldname for f in meta.fields}

    # Try common names in order
    def pick(*candidates):
        for c in candidates:
            if c in brand_fields:
                return c
        return None

    father_key = pick("father", "parent_brand", "parent", "custom_father")
    root_key   = pick("root", "is_root", "custom_root")

    # Build fields list safely (only include what exists)
    fields = ["name"]
    if father_key: fields.append(father_key)
    if root_key:   fields.append(root_key)

    brands = frappe.get_all("Brand", fields=fields)

    # ---------- determine root brands ----------
    # roots_by_flag: brands with root_key == 1 (if available)
    roots_by_flag = set()
    if root_key:
        for b in brands:
            try:
                if int(b.get(root_key) or 0) == 1:
                    roots_by_flag.add(b["name"])
            except Exception:
                pass

    # Helper: read father for a brand
    def get_father(bname):
        if not father_key:
            return None
        row = next((x for x in brands if x["name"] == bname), None)
        if not row:
            return None
        return (row.get(father_key) or None)

    # If no flag set, fallback roots = brands without father (when father_key exists)
    if not roots_by_flag and father_key:
        roots_by_flag = {b["name"] for b in brands if not (b.get(father_key) or None)}

    # If still nothing, final fallback: every brand is its own root
    if not roots_by_flag:
        roots_by_flag = {b["name"] for b in brands}

    # Map any brand -> a root brand
    cache_root = {}
    def find_root(brand_name, depth=0):
        if not brand_name:
            return None
        if brand_name in cache_root:
            return cache_root[brand_name]
        if brand_name in roots_by_flag:
            cache_root[brand_name] = brand_name
            return brand_name
        if depth > 20 or not father_key:
            # no father chain available or too deep; treat itself as root if nothing else
            cache_root[brand_name] = brand_name if brand_name in roots_by_flag else None
            return cache_root[brand_name]
        parent = get_father(brand_name)
        if not parent:
            cache_root[brand_name] = brand_name if brand_name in roots_by_flag else None
            return cache_root[brand_name]
        res = find_root(parent, depth + 1)
        cache_root[brand_name] = res
        return res

    # ---------- Items: map item_code -> root brand ----------
    items = frappe.get_all("Item", fields=["name", "brand"], filters={"disabled": 0})
    item_root = {}
    for it in items:
        rb = find_root(it.get("brand")) if it.get("brand") else None
        if rb:
            item_root[it["name"]] = rb

    if not item_root:
        return {"root_brands": sorted(roots_by_flag), "warehouses": []}

    # ---------- Warehouses ----------
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
        limit_page_length=10000,
    )
    if not wh_rows:
        return {"root_brands": sorted(roots_by_flag), "warehouses": []}

    wh_names = [w["name"] for w in wh_rows]

    # ---------- Bins ----------
    bins = frappe.get_all(
        "Bin",
        fields=["warehouse","item_code","actual_qty"],
        filters={"warehouse": ["in", wh_names]},
        limit_page_length=2000000,
    )

    qty_map   = defaultdict(float)  # (warehouse, root_brand) -> qty
    item_sets = defaultdict(set)    # (warehouse, root_brand) -> items with qty>0

    for b in bins:
        it = b["item_code"]
        rb = item_root.get(it)
        if not rb:
            continue
        wh  = b["warehouse"]
        qty = float(b.get("actual_qty") or 0)
        qty_map[(wh, rb)] += qty
        if qty > 0:
            item_sets[(wh, rb)].add(it)

    # Brand ordering (optionally limit to top-K)
    brand_totals = defaultdict(float)
    for (wh, rb), q in qty_map.items():
        brand_totals[rb] += q

    brands_order = sorted(roots_by_flag, key=lambda r: (-brand_totals.get(r, 0), r))
    if limit_brands > 0:
        brands_order = brands_order[:limit_brands]

    out_wh = []
    for w in wh_rows:
        brands_payload = []
        for rb in brands_order:
            q = qty_map.get((w["name"], rb), 0.0)
            c = len(item_sets.get((w["name"], rb), set()))
            brands_payload.append({"root_brand": rb, "qty": round(q, 6), "item_count": int(c)})
        row = dict(w)
        row["brands"] = brands_payload
        out_wh.append(row)

    return {
        "root_brands": list(brands_order),
        "warehouses": out_wh,
    }
