# Declared prospective M1 receipt continuity (offline)

`app.prospective_receipt_continuity.audit_declared_m1_receipt_continuity`
compares two **retained, append-only, caller-declared** completed-minute
receipt checkpoints. It is intentionally separate from the Twelve Data HTTP
adapter, Trading 212 metadata probe, broker order systems, and live charts.

This catches a specific provenance failure that a per-checkpoint gap census
cannot catch: an old minute's OHLC or original receipt timestamp can be
rewritten between otherwise individually complete checkpoints. It also
reports removed old rows, late additions to the old expected population,
backdated newly added receipt timestamps, and genuinely new expected minutes.

## Contract

- Pass two separately compiled `ExpectedM1Manifest` instances and their
  exact retained receipt rows. Both manifests are reconstructed by the
  existing `audit_m1_receipts_against_manifest` implementation.
- Source provider, exact symbol, venue, price side, calendar ID, calendar
  revision, and calendar-source declaration must match.
- The current observation time must advance, and the old expected-minute
  population must remain an exact prefix of the new population. Changed
  historical expected minutes require a separate explicit calendar review.
- Retain original `received_at_utc` for every old minute. Do **not** replace
  retained rows with newly polled provider rows stamped at poll time.
- Every duplicate, missing/unexpected minute, stale receipt, late receipt,
  rewritten OHLC/receipt timestamp, removed old row, backfill or backdated
  newly added receipt forces `REVIEW_REQUIRED`. Both underlying censuses
  must independently pass for a clean internal continuity result.
- Input sizes, timestamp alignment, OHLC shape, and sample limits are
  bounded by the existing census. The output contains counts, SHA-256 input
  fingerprints and at most 50 UTC timestamp samples, **not price arrays**.
- The clean status is `INTERNAL_CONTINUITY_ONLY_NOT_LIVE`, **never**
  authenticated data, exchange-session verification, market freshness or
  permission to execute orders.

### Synthetic example

```python
from app.expected_bar_manifest import compile_expected_m1_manifest
from app.prospective_receipt_continuity import audit_declared_m1_receipt_continuity

# Use the two synthetic fixture manifests and retained rows in
# backend/tests/test_prospective_receipt_continuity.py.
# The audit refuses a changed old OHLC or changed old received_at_utc.
```

Run: `cd backend && PYTHONPATH=. pytest -q tests/test_prospective_receipt_continuity.py`

## Limitations and activation blockers

This is an **offline internal consistency check**, not a durable journal or
cryptographic vendor signature. A caller could fabricate both checkpoints,
receipt timestamps, calendar declarations and fingerprints. Production use
requires independent, instrument-specific source licensing and entitlement,
an authenticated completed-candle provider, independently verified session
and holiday calendars with DST, server-owned append-only receipt storage,
monotonic clock evidence, correction/void policy, replay safeguards, backup
restoration, rollback rehearsal and health checks.

Do not treat BID-only HistData archives, a marketing data feed, a Twelve Data
normalized candle, or Trading 212 Invest/Stocks ISA instrument metadata as
executable Gold/WTI/Nasdaq CFD bid/ask quotes. The official Trading 212 public
API is not documented for CFD accounts. This change performs **no** API calls,
database writes, broker connection, polling, order execution, or deployment.
Keep PR #65 draft until the independent release gates are satisfied.
