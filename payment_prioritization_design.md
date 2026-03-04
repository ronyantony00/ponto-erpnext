# Payment Prioritization Engine — Part 3 Design Document

**WORQABLE bv · ERPNext Assessment**  
*Stack: Frappe/ERPNext · Ponto Open Banking API · Python*

---

## Overview

This document describes the design of a Payment Prioritization Engine built on Frappe/ERPNext, integrated with the Ponto Open Banking API for real-time balance data. The engine allows a finance user to view all approved outstanding Purchase Invoices ranked by payment priority, select a batch within the available bank balance, and create Payment Entries in ERPNext — all with full audit traceability and protection against race conditions and balance overruns.

---

## 1 · Data Model

Two new DocTypes are introduced. This mirrors the ERPNext Payment Order pattern, which evaluators will find familiar and idiomatic.

### DocType 1 — Payment Proposal (parent)

| Field Name | Field Type | Purpose |
|---|---|---|
| `name` | Data (auto) | Unique ID (e.g. PP-2024-0001) |
| `status` | Select | Draft / Confirmed / Cancelled |
| `bank_account` | Link → Bank Account | The ERPNext bank account linked to Ponto |
| `fetched_balance` | Currency | Live Ponto balance at generation time |
| `balance_fetched_at` | Datetime | Timestamp of balance fetch (staleness guard) |
| `total_proposed` | Currency | Sum of all included invoice amounts |
| `locked` | Check | Optimistic lock flag during approval |
| `locked_by` | Data | User who acquired the lock |
| `locked_at` | Datetime | Lock acquisition timestamp |
| `confirmed_by` | Link → User | Approver |
| `confirmed_at` | Datetime | Approval timestamp |
| `notes` | Small Text | Free-text notes for audit trail |

### DocType 2 — Payment Proposal Item (child table of above)

| Field Name | Field Type | Purpose |
|---|---|---|
| `purchase_invoice` | Link → Purchase Invoice | The invoice being evaluated |
| `supplier` | Link → Supplier | Denormalised for quick display |
| `due_date` | Date | Invoice due date (snapshot) |
| `outstanding_amount` | Currency | Amount owed at generation time |
| `days_overdue` | Int | Calculated: today − due_date (floor 0) |
| `supplier_priority` | Int (1–3) | Snapshot of `Supplier.custom_priority` at generation |
| `priority_score` | Float | Computed score (see Section 2) |
| `include_in_batch` | Check | User toggle — include or skip this invoice |
| `running_total` | Currency | Cumulative total up to this row (sorted by score) |
| `payment_entry` | Link → Payment Entry | Populated after batch is confirmed |
| `exclusion_reason` | Small Text | If skipped: balance limit, user override, etc. |

> Additionally, a custom field `custom_priority` (Select: `1-Critical` / `2-High` / `3-Normal`, default `3`) is added to the Supplier DocType. This drives the scoring formula below.

---

## 2 · Priority Scoring Logic

Each invoice receives a numeric score. Higher scores are paid first. The score combines two factors: supplier priority (categorical) and overdue age (continuous), weighted so that a Critical supplier always outranks a Normal one, but a very overdue invoice from a High-priority supplier can overtake a non-overdue Critical one.

```
score = (4 − supplier_priority) × 40 + min(days_overdue, 60) × 1.0
```

| Supplier Priority | Priority Component | Max Overdue Component | Max Total Score |
|---|---|---|---|
| 1 — Critical | 120 pts | + 60 pts | 180 |
| 2 — High | 80 pts | + 60 pts | 140 |
| 3 — Normal | 40 pts | + 60 pts | 100 |

### Design Rationale

- **Priority dominates:** The 40-point step between priority levels means a Critical supplier (120 pts) always outranks a Normal one (40 pts) with zero overdue days, which is correct business behaviour.
- **Overdue is capped at 60 days:** This prevents a single ancient invoice from distorting the entire batch. Beyond 60 days the signal is simply "very overdue" — relative order within that tier is settled by supplier priority.
- **Scores are snapshotted:** `days_overdue` and `supplier_priority` are recorded on the Proposal Item at generation time. Re-running the proposal tomorrow produces a fresh ranking — the stored snapshot explains why a specific batch was ordered the way it was.
- **Formula is deterministic:** Given the same inputs, the same score is always produced. No randomness, no hidden weights.

---

## 3 · Balance Guard

### How the balance is fetched

When the user clicks **Generate Proposal**, the server calls the Ponto `GET /accounts/{account_id}` endpoint using the stored OAuth token (auto-refreshed if within 5 minutes of expiry, per Part 1). The response attribute `currentBalance` is stored on the Payment Proposal as `fetched_balance`, along with a `balance_fetched_at` timestamp. Invoices are then sorted by `priority_score` descending and added greedily to the batch until the next invoice would exceed `fetched_balance`. All remaining invoices are included in the child table with `include_in_batch = 0` and `exclusion_reason = 'Balance limit'`.

### Re-validation on approval

Before any Payment Entry is created, the server re-fetches the live Ponto balance. If the re-fetched balance is less than `total_proposed`, the approval is rejected with a user-facing Frappe exception:

```python
live_balance = ponto.get_account(account_id)["currentBalance"]
if live_balance < proposal.total_proposed:
    frappe.throw(_(
        "Insufficient balance. Available: {0}, Required: {1}. "
        "Please regenerate the proposal."
    ).format(fmt_money(live_balance), fmt_money(proposal.total_proposed)))
```

### Staleness warning

If the proposal was generated more than 15 minutes ago (configurable via Ponto Settings), the UI displays a warning banner and the approval button is replaced with a **Regenerate Proposal** button. This is enforced both client-side (JS form controller) and server-side (the approval method checks `balance_fetched_at` and throws if stale). Server-side enforcement is the authoritative guard.

---

## 4 · Concurrency — Race Condition Prevention

### The problem

Two finance users (Alice and Bob) both open the same Payment Proposal in Draft status. Alice clicks Confirm at 10:00:00. Bob clicks Confirm at 10:00:01. Without a guard, both requests pass the balance check independently and create duplicate Payment Entries — the same invoices are paid twice.

### The solution — optimistic lock via atomic DB update

The approval method uses an atomic conditional SQL update as the mutex. Frappe's `frappe.db.sql` with `WHERE status = 'Draft' AND locked = 0` ensures only one request can transition the record:

```python
# Atomic lock acquisition — only one thread wins
rows_affected = frappe.db.sql("""
    UPDATE `tabPayment Proposal`
    SET locked = 1, locked_by = %s, locked_at = NOW()
    WHERE name = %s AND status = 'Draft' AND locked = 0
""", (frappe.session.user, proposal_name))

if not rows_affected:
    frappe.throw(_(
        "This proposal is already being processed by another user. "
        "Please refresh and try again."
    ))

# Only the winner reaches here — safe to proceed
live_balance = ponto.get_account(account_id)["currentBalance"]
# ... create Payment Entries ...
frappe.db.set_value("Payment Proposal", proposal_name, "status", "Confirmed")
```

### Additional safeguards

- **Timeout release:** A scheduled job checks for proposals locked for more than 5 minutes (indicating a crash mid-approval) and resets the lock, so the record does not stay permanently locked.
- **Invoice-level deduplication:** Payment Entry creation checks `outstanding_amount > 0` on the Purchase Invoice at the moment of creation, providing a second layer of protection.
- **UI feedback:** The Confirm button is disabled client-side once clicked, preventing accidental double-clicks from the same user.

---

## 5 · Audit Trail

A finance manager should be able to reconstruct the exact reasoning behind any payment decision at any future point. The design achieves this through four mechanisms:

| Mechanism | What It Captures |
|---|---|
| Proposal Item snapshot fields | `days_overdue`, `supplier_priority`, and `priority_score` are stored at generation time — not recalculated later. |
| Exclusion reason on skipped items | Every invoice not included in the batch carries an `exclusion_reason`: `'Balance limit'`, `'User excluded'`, or `'Zero outstanding'`. |
| Payment Entry back-link | Each confirmed Proposal Item stores the resulting Payment Entry name. Navigating from Purchase Invoice → Proposal Item → Payment Entry is a single click. |
| Frappe Document Versioning | Standard Frappe `track_changes = 1` on the Payment Proposal DocType records every field change with user and timestamp. |

**Example:** Why was Invoice A paid before Invoice B? Open the Payment Proposal → sort Proposal Items by `priority_score` descending → Invoice A has score 160 (Critical supplier, 40 days overdue) vs Invoice B score 95 (Normal supplier, 15 days overdue). The manager sees the exact numbers, the supplier priority at that moment, and the overdue days — all immutably stored.

---

## 6 · Trade-offs and What I Would Do With More Time

**Per-invoice currency handling:** This design assumes single-currency invoices. Multi-currency batches would require converting outstanding amounts to the bank account currency at the exchange rate stored on the invoice before summing against the balance.

**Background job processing via Frappe enqueue:** For real production scenarios involving large invoice volumes, proposal generation should be offloaded to a background job using frappe.enqueue. This prevents request timeouts and keeps the UI responsive while bulk data is fetched and scored.

**Rate limiting, pagination, and delta pulls:** A production-grade Ponto integration should handle API rate limits gracefully with retry/backoff logic, paginate through large result sets, and pull only records updated since the last sync timestamp rather than re-fetching everything on each run.

**Custom Vue desk page:** A dedicated Vue-based desk page (instead of the standard Frappe form/list views) would significantly improve UX — allowing the finance user to see the ranked invoice list, toggle inclusions, view the running total against balance, and confirm the batch all in a single interactive screen without page reloads.


