# Durable one-shot provider credit reservations (Loop 1)

This is an **offline, opt-in SQLite reservation gate**, not a live-feed or
provider entitlement integration. It does not contact Twelve Data, validate
license contracts, configure accounts, or schedule requests.

`app.prospective_twelvedata_receipt.review_twelvedata_completed_m1` now
refuses a potentially billable request unless **all** conditions hold:

1. The existing exact-boolean, per-call owner credit and data-rights approvals.
2. The existing exact XAU/USD mapping and intact, completed-bar UTC manifest.
3. A previously provisioned durable SQLite ledger with a budget for the
   server's **current UTC day** and fixed purpose `completed-m1-review`.
4. An unused 32-character lowercase hex request ID and valid manifest digest.
5. A successful, atomic **one-credit reservation before the HTTP request**.

The ledger is never provisioned automatically by the receipt bridge. Budget
provisioning requires `owner_confirmed=True`, a UTC date, a positive maximum
of 1–5,000 credits and operator-provided SHA-256 references for independently
checked entitlement and data-rights evidence. These are **self-declared
references, not cryptographic proof of legal rights**. Only an authenticated,
owner-controlled operator workflow should call the provisioning function.

Example for an offline, synthetic development fixture (do not run against a
real provider or reuse these fingerprints as evidence):

```python
from app.provider_credit_budget import provision_daily_budget
provision_daily_budget(
    "/absolute/durable/private/provider-credits.sqlite",
    utc_day="2026-10-26", max_credits=2,
    entitlement_evidence_sha256="a" * 64,
    rights_evidence_sha256="b" * 64,
    owner_confirmed=True,
)
```

The real bridge requires `budget_db_path` and a fresh
`budget_request_id` alongside the existing owner approvals. It reserves one
credit even when the vendor subsequently fails, times out, rejects a key, or
returns malformed data. **Never automatically refund or retry an uncertain
provider request.** Replayed request IDs fail closed; concurrent SQLite writers
serialize with `BEGIN IMMEDIATE`. The policy cannot be silently increased,
overwritten or rolled over to a new day.

## Important boundaries

- The SQLite file must live on **durable, backed-up, private, single-host
  storage**. An ephemeral Render filesystem is **not acceptable**. No
  multi-host distributed lock, PostgreSQL migration, API route, owner identity
  authentication, account-secret storage or vendor usage reconciliation exists.
- SQLite file contents are not tamper-evident or cryptographically signed;
  operator-provided SHA-256 references are not independent license evidence.
  The clock is the backend system clock and is not independently attested.
- A reservation is a **local spending ceiling**, not an exact statement of
  Twelve Data's billing, account usage, or contractual entitlement. The
  one-credit assumption applies only to this fixed one-symbol one-shot
  `/time_series` integration and must be rechecked against current official
  provider terms before activation.
- No persistent raw market-data archive, broker quote, executable spread,
  authenticated live feed, automatic polling, or real-money order is enabled.
- Deployment remains blocked pending source rights, expected-session and DST
  evidence, authenticated owner invocation, licensed staging acceptance,
  private production restore/rollback/health drills, and exact-head CI.

Synthetic tests:

```bash
cd backend
PYTHONPATH=. pytest -q tests/test_provider_credit_budget.py tests/test_prospective_twelvedata_receipt.py
```

Official vendor references: https://twelvedata.com/docs and
https://docs.trading212.com/api (Trading 212 public API does not cover CFDs).
