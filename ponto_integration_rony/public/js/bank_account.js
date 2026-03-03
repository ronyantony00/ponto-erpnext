// Copyright (c) 2025, Ponto Integration Rony and contributors
// MIT License. See license.txt

// Add "Sync from Ponto" button on Bank Account form when this account is linked in Ponto Settings
frappe.ui.form.on("Bank Account", {
	refresh: function (frm) {
		if (frm.doc.__islocal) return;
		frappe.call({
			method: "frappe.client.get_value",
			args: {
				doctype: "Ponto Settings",
				filters: {},
				fieldname: "bank_account",
			},
			callback: function (r) {
				if (r.exc || !r.message) return;
				const linked_bank_account = r.message.bank_account;
				if (linked_bank_account && linked_bank_account === frm.doc.name) {
					frm.add_custom_button(__("Sync from Ponto"), function () {
						frappe.call({
							method: "ponto_integration_rony.ponto_integration_rony.doctype.ponto_settings.ponto_settings.sync_ponto_transactions",
							args: { bank_account_name: frm.doc.name },
							freeze: true,
							callback: function (resp) {
								if (resp.exc) return;
								const msg = resp.message;
								const created = msg && msg.created != null ? msg.created : 0;
								const total = msg && msg.total_fetched != null ? msg.total_fetched : 0;
								frappe.msgprint({
									title: __("Sync complete"),
									message: __("Created {0} Bank Transaction(s) from {1} Ponto transaction(s).", [
										created,
										total,
									]),
									indicator: "green",
								});
								frm.reload_doc();
							},
						});
					});
				}
			},
		});
	},
});
