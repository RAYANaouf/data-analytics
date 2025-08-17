// Copyright (c) 2025, rayan aouf and contributors
// For license information, please see license.txt

// frappe.ui.form.on("Item Weight Measure", {
// 	refresh(frm) {

// 	},
// });
// File: your_app/your_app/doctype/item_weight/item_weight.js

frappe.ui.form.on("Item Weight Measure", {
    onload(frm) {
      // Smart defaults for empty dates: last ~12 months
      const setDefaultDates = () => {
        const today = frappe.datetime.get_today();
        // first day roughly 12 months ago (safe fallback)
        const d = frappe.datetime.add_months(today, -12);
        const firstDay = frappe.datetime.str_to_obj(d);
        firstDay.setDate(1);
        const fromStr = frappe.datetime.obj_to_str(firstDay);
  
        if (!frm.doc.from_date) frm.set_value("from_date", fromStr);
        if (!frm.doc.to_date) frm.set_value("to_date", today);
      };
  
      setDefaultDates();
    },
  
    refresh(frm) {
      // Helpful intro
      frm.set_intro(
        __("Choose <b>Company</b> and (optionally) <b>Warehouse</b>. " +
           "Set a date range or leave defaults (last ~12 months). " +
           "Click <b>Generate</b> to compute the best month per item."),
        "blue"
      );
  
      
    },

    generate_btn(frm) {
        frappe.call({
            method: "data_analytics.data_analytics.doctype.item_weight_measure.item_weight_measure.generate_item_best_month",
            args: {
                company: frm.doc.company,
                warehouse: frm.doc.warehouse,
                from_date: frm.doc.from_date,
                to_date: frm.doc.to_date,
            },
            freeze: true,
            freeze_message: __("Computing…"),
            callback: (r) => {
                console.log("my result ===> " , r);
                frappe.msgprint("Done");
                r.message.results.forEach((item) => {
                    frm.add_child("items", {
                        item: item.item_code,
                        qty: item.total_qty,
                        date: item.ym,
                    });
                });
                frm.refresh_field("items");
            }
        });
    }
});
  
  