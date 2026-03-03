# Copyright (c) 2025, Ponto Integration Rony and contributors
# MIT License. See license.txt

"""
Minimal Ponto API client for OAuth2 client credentials and transaction listing.
See https://documentation.myponto.com for full API reference.
Official docs: token at https://api.myponto.com/oauth2/token with Basic auth (base64 client_id:client_secret).
"""

import base64
import frappe
from frappe import _
import requests
from urllib.parse import urljoin

# Ponto API base (token and API use same host; sandbox vs production by credentials)
PONTO_API_BASE = "https://api.myponto.com"


def fetch_access_token(client_id: str, client_secret: str, use_sandbox: bool = True) -> dict:
	"""
	Obtain OAuth2 access token using client credentials flow.
	Uses Authorization: Basic base64(client_id:client_secret) per Ponto docs.
	Returns dict with access_token and expires_in (seconds).
	Raises frappe.ValidationError on API errors.
	"""
	url = urljoin(PONTO_API_BASE + "/", "oauth2/token")
	credentials = f"{client_id}:{client_secret}"
	encoded = base64.b64encode(credentials.encode("utf-8")).decode("ascii")
	headers = {
		"Content-Type": "application/x-www-form-urlencoded",
		"Accept": "application/json",
		"Authorization": f"Basic {encoded}",
	}
	payload = {"grant_type": "client_credentials"}

	try:
		resp = requests.post(url, data=payload, headers=headers, timeout=30)
		resp.raise_for_status()
	except requests.exceptions.RequestException as e:
		msg = _ponto_error_message(e, _token_status_hint=True)
		frappe.throw(_("Ponto API error: {0}").format(msg))

	data = resp.json()
	access_token = data.get("access_token")
	expires_in = data.get("expires_in", 1800)  # default 30 min
	if not access_token:
		frappe.throw(_("Ponto API did not return an access token"))
	return {"access_token": access_token, "expires_in": expires_in}


def get_transactions(access_token: str, account_id: str, limit: int = 10, use_sandbox: bool = True) -> list:
	"""
	Fetch transactions for the given Ponto account_id.
	Returns list of transaction objects (Ponto API format).
	Raises frappe.ValidationError on API errors.
	"""
	url = urljoin(PONTO_API_BASE + "/", f"accounts/{account_id}/transactions")
	headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
	params = {"page[limit]": limit}

	try:
		resp = requests.get(url, headers=headers, params=params, timeout=30)
		resp.raise_for_status()
	except requests.exceptions.RequestException as e:
		msg = _ponto_error_message(e, _token_status_hint=False)
		frappe.throw(_("Ponto API error: {0}").format(msg))

	data = resp.json()
	# Ponto returns { "data": [ { "id", "type", "attributes": { ... } }, ... ] }
	return data.get("data") or []


# --- Error handling (status messages and message builder) ---

# User-facing error messages by HTTP status (Ponto: 400, 401, 403, 404, 500).
# Key: (status_code, token_hint). Value: (message or format string, format_with_api_msg).
# Lookup: (code, hint) then (code, None) so one entry can cover both token and API calls.
PONTO_STATUS_MESSAGES = {
	(401, True): (_("Invalid client credentials (401). Check Client ID and Client Secret in Ponto Settings."), False),
	(401, False): (_("Invalid or expired access token (401). Use Refresh Token or Fetch Token in Ponto Settings."), False),
	(403, None): (_("Access forbidden (403). {0}"), True),
	(404, False): (_("Account not found (404). Use the Ponto account UUID from GET /accounts as Account ID, not the IBAN."), False),
	(500, None): (_("Ponto server error (500). Try again later. {0}"), True),
}


def _ponto_error_message(e: requests.exceptions.RequestException, _token_status_hint: bool = False) -> str:
	"""Build a user-facing message from a Ponto API exception. Handles 400, 401, 403, 404, 500."""
	msg = str(e)
	resp = getattr(e, "response", None)
	if resp is not None:
		try:
			body = resp.json()
			errors = body.get("errors") or []
			if errors and isinstance(errors, list):
				detail = errors[0].get("detail") or errors[0].get("code") or msg
				msg = detail
			else:
				msg = body.get("error_description") or body.get("detail") or body.get("error") or msg
		except Exception:
			pass
		code = resp.status_code
		key = (code, _token_status_hint)
		entry = PONTO_STATUS_MESSAGES.get(key) or PONTO_STATUS_MESSAGES.get((code, None))
		if entry:
			template, format_with_api_msg = entry
			msg = template.format(msg) if format_with_api_msg else template
	return msg
