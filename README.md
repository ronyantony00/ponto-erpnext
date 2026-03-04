# Ponto Integration

Integration app that connects [Ponto](https://myponto.com) with ERPNext: OAuth2 token management and syncing bank transactions from Ponto into ERPNext Bank Transactions.

**Features:**

- **Ponto Settings** (single doctype): Store client credentials, fetch/refresh OAuth2 access token, link one Ponto account to an ERPNext Bank Account.
- **Sync from Ponto**: On the linked Bank Account form, a button fetches the last 10 Ponto transactions and creates Bank Transaction records (with deduplication by Ponto transaction ID).
- Token is refreshed automatically when it is within 5 minutes of expiry (when you run Sync or Refresh Token).

---

## Installation

### Prerequisites

- A Frappe bench with **ERPNext** installed.
- A Ponto (or Ponto sandbox) integration with **Client ID** and **Client Secret** from the [Ponto dashboard](https://documentation.myponto.com/).

### Steps

1. **Get and install the app**

   ```bash
   cd /path/to/your/bench
   bench get-app <URL_OF_THIS_REPO> --branch develop
   bench --site <site-name> install-app ponto_integration_rony
   ```

2. **Restart and migrate (if needed)**

   ```bash
   bench restart
   bench migrate
   ```

3. **Configure Ponto Settings**

   - Go to **Ponto Settings** (search in the Desk or via Setup).
   - Enter **Client ID** and **Client Secret** from your Ponto integration.
   - Check **Use Sandbox** if you use Ponto sandbox credentials.
   - Click **Fetch Token**; after success, **Access Token** and **Token Expiry** will be set.
   - Set **Account ID**: the Ponto account **UUID** (not the IBAN). To get it:
     - Call `GET https://api.myponto.com/accounts?page[limit]=10` with header `Authorization: Bearer <your_access_token>`.
     - Use the `id` of the account you want (e.g. `c3f966d6-eaa9-4074-8799-3b4acc2c3a66`).
   - create a Bank and Bank Account in ERPNext if not exists
   - Link **Bank Account** to the ERPNext Bank Account that corresponds to this Ponto account.

4. **Sync transactions**

   - Open the **Bank Account** that you linked in Ponto Settings.
   - Use the **Sync from Ponto** button to fetch the last 10 transactions and create Bank Transactions (duplicates are skipped by reference number).

---

## Validation (Assessment Acceptance Checklist)

Use this quick sequence before submission:

1. **Token fetch**
   - Open **Ponto Settings** and click **Fetch Token**.
   - Confirm `access_token` and `token_expiry` are populated.

2. **5-minute auto refresh**
   - Temporarily set `token_expiry` to a time within the next 5 minutes.
   - Click **Refresh Token** (or run **Sync from Ponto**).
   - Confirm token refresh occurs and `token_expiry` is extended.

3. **First sync creates records**
   - Open the linked **Bank Account** and click **Sync from Ponto**.
   - Confirm `Bank Transaction` records are created.

4. **Second sync skips duplicates**
   - Run **Sync from Ponto** again immediately.
   - Confirm no duplicates are created for existing `reference_number` values.

5. **Deposit/withdrawal mapping check**
   - Verify a positive amount maps to `deposit` and negative amount maps to `withdrawal`.
   - Verify both fields are never populated simultaneously on one record.

---

## Assumptions

- **ERPNext** is installed; the app uses the standard **Bank Account** and **Bank Transaction** doctypes.
- **Single Ponto account** per installation: one Ponto Settings record, one linked Bank Account.
- **Account ID** in Ponto Settings is the Ponto account UUID from `GET /accounts`, not the IBAN.
- **Ponto API**: Token and API use the same host (`https://api.myponto.com`); sandbox vs production is determined by credentials. OAuth2 uses **client_credentials** only (no refresh_token).
- **Transaction shape**: Sync expects Ponto transaction objects with `id`, `attributes.valueDate`, `attributes.amount`, `attributes.description`, `attributes.counterpartName`, `attributes.counterpartReference`. If the API response format changes, mapping in the app may need to be updated.
- **Currency**: Taken from the linked Bank Account’s Account → account currency; else Company default; else global default; else EUR.

---

## Known limitations

- **Sync limit**: Only the **last 10** Ponto transactions are fetched per sync; there is no pagination or full-history import.
- **Manual sync**: Sync is triggered only by the user (button on Bank Account). There is no webhook or scheduled job to sync automatically.
- **One bank account**: Only one ERPNext Bank Account can be linked in Ponto Settings; the Sync button appears only on that Bank Account form.
- **No payment initiation**: The app does **not** create or submit payments in Ponto; it only reads transactions. Payment initiation is out of scope.
- **Token refresh**: Token is refreshed only when an action is run (e.g. Sync or Refresh Token) and the stored token is within 5 minutes of expiry. There is no background job that refreshes the token proactively.
- **Date handling**: Transaction dates from Ponto are mapped as-is (e.g. value date); timezone or booking-date differences can cause small date mismatches compared to the Ponto UI.

---

## Contributing

This app uses **pre-commit** for formatting and linting. Install and enable it:

```bash
cd apps/ponto_integration_rony
pre-commit install
```

Tools used: **ruff**, **eslint**, **prettier**, **pyupgrade**.

---

## License

MIT
