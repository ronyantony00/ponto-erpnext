# Copyright (c) 2025, Ponto Integration Rony and contributors
# MIT License. See license.txt

from datetime import datetime, timedelta, timezone

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import get_datetime, getdate

from ponto_integration_rony.ponto_api import fetch_access_token, get_transactions


class PontoSettings(Document):
	def get_client_secret(self):
		"""Return client secret for server-side use only. Never expose in API responses."""
		return self.get_password("client_secret")

	@frappe.whitelist()
	def fetch_token(self):
		"""Obtain OAuth2 access token from Ponto and store it."""
		if not self.client_id:
			frappe.throw(_("Client ID is required"))
		secret = self.get_client_secret()
		if not secret:
			frappe.throw(_("Client Secret is required"))
		use_sandbox = bool(self.get("use_sandbox", True))
		result = fetch_access_token(self.client_id, secret, use_sandbox=use_sandbox)
		expires_in = result.get("expires_in", 1800)
		self.access_token = result["access_token"]
		self.token_expiry = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(seconds=expires_in)
		self.save(ignore_permissions=True)
		frappe.db.commit()
		return {"message": _("Token fetched successfully")}

	@frappe.whitelist()
	def ensure_token(self):
		"""Refresh token if it expires within 5 minutes. Uses client_credentials (no refresh_token in Ponto API)."""
		now = datetime.now(timezone.utc).replace(tzinfo=None)
		threshold = now + timedelta(minutes=5)
		if self.token_expiry:
			expiry_dt = get_datetime(self.token_expiry)  # handles str → datetime
			if expiry_dt and expiry_dt <= threshold:
				self.fetch_token()
				return {"refreshed": True, "message": _("Token refreshed")}
		else:
			# No token yet
			self.fetch_token()
			return {"refreshed": True, "message": _("Token fetched")}
		return {"refreshed": False, "message": _("Token still valid")}

	@staticmethod
	@frappe.whitelist()
	def sync_ponto_transactions(bank_account_name: str):
		"""Fetch last 10 Ponto transactions for the linked account and create Bank Transactions."""
		settings = frappe.get_single("Ponto Settings")
		if not settings.bank_account:
			frappe.throw(_("Please set Bank Account in Ponto Settings"))
		if settings.bank_account != bank_account_name:
			frappe.throw(
				_("This Bank Account is not linked to Ponto Settings. Link it in Ponto Settings first.")
			)
		settings.ensure_token()
		if not settings.account_id:
			frappe.throw(_("Please set Account ID in Ponto Settings"))
		use_sandbox = bool(settings.get("use_sandbox", True))
		transactions = get_transactions(
			settings.access_token, settings.account_id, limit=10, use_sandbox=use_sandbox
		)
		created = _create_bank_transactions_from_ponto(transactions, settings.bank_account)
		return {"created": created, "total_fetched": len(transactions)}


# Expose for RPC (get_attr looks up module.sync_ponto_transactions)
sync_ponto_transactions = PontoSettings.sync_ponto_transactions


def _create_bank_transactions_from_ponto(transactions: list, bank_account: str) -> int:
	"""Map Ponto transactions to ERPNext Bank Transaction. Dedupe by reference_number. Returns count created."""
	currency = frappe.get_cached_value("Bank Account", bank_account, "account")
	if currency:
		currency = frappe.get_cached_value("Account", currency, "account_currency")
	if not currency:
		currency = frappe.get_cached_value("Company", frappe.get_cached_value("Bank Account", bank_account, "company"), "default_currency")
	if not currency:
		currency = frappe.defaults.get_global_default("currency") or "EUR"
	created = 0
	for txn in transactions:
		txn_id = txn.get("id")
		if not txn_id:
			continue
		if frappe.db.exists("Bank Transaction", {"reference_number": txn_id}):
			continue
		attrs = txn.get("attributes") or {}
		amount = attrs.get("amount")
		if amount is None:
			continue
		deposit = 0.0
		withdrawal = 0.0
		if isinstance(amount, (int, float)):
			if amount > 0:
				deposit = float(amount)
			else:
				withdrawal = abs(float(amount))
		value_date = attrs.get("valueDate")
		date_val = getdate(value_date) if value_date else getdate()
		doc = frappe.get_doc(
			{
				"doctype": "Bank Transaction",
				"reference_number": txn_id,
				"date": date_val,
				"deposit": deposit,
				"withdrawal": withdrawal,
				"description": attrs.get("description") or "",
				"bank_party_name": attrs.get("counterpartName") or "",
				"bank_party_iban": attrs.get("counterpartReference") or "",
				"bank_account": bank_account,
				"currency": currency,
			}
		)
		doc.insert(ignore_permissions=True)
		created += 1
	return created
