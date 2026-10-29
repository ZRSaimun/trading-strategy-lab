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
6. **No reservation within the previous rolling 60 seconds**, regardless
   of daily allowance or UTC date boundary. The fixed one-shot integration
   allows at most one attempt per rolling minute; the check and INSERT share
   one SQLite write transaction. A future-dated reservation blocks attempts
   after a backwards clock adjustment.

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
overwritten or rolled over to a new day. Requests less than 60 seconds
after any earlier reservation are denied, **including across UTC midnight**;
a new calendar-minute boundary is not enough. Another attempt requires a
**new** request ID, renewed per-call approvals and a full 60-second separation.
A failed or uncertain request still consumes its rolling-minute slot and daily credit.

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

## Private-ledger filesystem preflight

Before provisioning or reserving, the bridge now fails closed unless the
**immediate ledger directory** is owned by the running service user and
has no group/other permission bits (typically `0700`). Any existing ledger
must be an owner-owned regular file with no group/other permission bits
(typically `0600`) and exactly one hard link. Symbolic-link ledgers,
shared directories, hard-linked databases and publicly readable ledgers are
rejected before SQLite opens them. First creation uses exclusive
`O_NOFOLLOW` where supported and owner-only file permissions.

These checks reduce accidental exposure and common filesystem aliasing
hazards; they do **not** make path validation race-free, inspect every ancestor
directory or mount/ACL, prove backups, or secure a compromised host. Operators
must provision a dedicated private durable directory and verify its mount,
backup restoration and host ownership independently. Existing ledgers with
permissive filesystem permissions will be refused until securely remediated.
No vendor request is made by these tests.

## Provider quota limitation (verified 26 October 2026)

Twelve Data's official support guidance distinguishes **per-minute API
credit limits** (paid plans) from the Basic plan's **daily quota**. The
provider's own `api-credits-used` and `api-credits-left` response headers
are not yet reconciled with this local ledger. This fixed integration
reserves one credit per call and limits local attempts to one per **rolling
60-second window**, including across UTC days, as a conservative safety gate;
this does **not** prove a provider
quota, account eligibility, price-side entitlement, billing or legal use
rights. A separate account-wide limit is still necessary if any other
application or API key consumes credits from the same provider account.

Official explanation: https://support.twelvedata.com/en/articles/5615854-credits

## Rolling-window boundary regression (29 October 2026)

The former UTC calendar-minute limiter allowed two reserved requests at
`HH:MM:59` and `HH:MM+1:00` (one second apart). The reservation query now
checks all ledger rows with `reserved_at_utc > now - 60` in the same atomic
SQLite transaction, regardless of daily policy, so the full cooldown is
preserved at minute and midnight boundaries. Future-dated rows also block
requests after a local clock rollback. Exact 60-second separation is allowed.
Synthetic tests cover the one-second boundary, midnight with separately
provisioned daily policies, and backward wall-clock movement. No vendor calls
or credits were consumed. This local clock is still not independently attested
and other applications using the provider account remain outside this ledger.

## Write-lock clock sampling (29 October 2026)

A contended SQLite `BEGIN IMMEDIATE` can wait before the reservation
transaction obtains its write lock. The reservation now samples the server UTC
clock **after** the write lock is acquired, so a delayed writer cannot record
the earlier pre-lock time and then admit a subsequent attempt less than 60
seconds after the actual reservation. The UTC-day policy lookup and rolling
cooldown both use this post-lock timestamp. A deterministic, zero-network
regression simulates a 70-second lock wait and checks the stored timestamp
and subsequent cooldown. This does not attest the system clock or coordinate
other applications using the same provider account.
