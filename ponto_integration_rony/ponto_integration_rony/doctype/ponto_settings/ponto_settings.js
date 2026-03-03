// Copyright (c) 2025, Ponto Integration Rony and contributors
// MIT License. See license.txt

frappe.ui.form.on("Ponto Settings", {
	refresh: function (frm) {
		if (frm.doc.client_id) {
			frm.add_custom_button(__("Fetch Token"), function () {
				frappe.call({
					method: "fetch_token",
					doc: frm.doc,
					freeze: true,
					callback: function (r) {
						if (r.exc) return;
						frappe.msgprint({
							title: __("Success"),
							message: r.message?.message || __("Token fetched successfully"),
							indicator: "green",
						});
						frm.reload_doc();
					},
				});
			});
			frm.add_custom_button(__("Refresh Token"), function () {
				frappe.call({
					method: "ensure_token",
					doc: frm.doc,
					freeze: true,
					callback: function (r) {
						if (r.exc) return;
						const msg = r.message?.message || __("Token refreshed");
						frappe.show_alert({ message: msg, indicator: "green" }, 5);
						frm.reload_doc();
					},
				});
			});
		}
	},
});
