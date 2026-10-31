# Declared completed-M1 receipt census (offline review only)

`app.prospective_receipt_census.audit_declared_m1_receipts` is a pure, bounded
review helper for a future **licensed, authenticated, read-only feed**. It makes
**no HTTP requests**, has **no credentials**, creates **no database rows**, does
not change any trading state, and never returns `live=true` or order approval.
It is not an active feed integration.

The caller supplies the exact `(provider, symbol, venue, price_side)` identity,
a server-observed UTC time, a set of **explicit expected completed UTC M1 start
minutes**, and individual source receipt rows with declared receipt times and
OHLC. No fallback instrument, symbol translation, DST conversion, or
session-calendar inference is performed. The caller must establish session
coverage and licensing independently. In particular, a list supplied by the
same untrusted source is **not** independent completeness evidence.

The audit fails closed for malformed or non-UTC-aligned timestamps, future or
incomplete bars, impossible receipt chronology, mixed identity/price sides,
invalid OHLC, missing expected-minute manifest, duplicate expected minutes,
non-finite values, extra fields (including fabricated `verified` flags), and
resource limits. It reports missing expected minutes separately from unexpected
observations, repeated timestamps separately from conflicting repeated prices,
late receipts separately from stale observation, and samples **timestamps only**.
No OHLC prices are returned. SHA-256 binds the caller-declared input for
reproducibility, **not** for source authentication.

Even when the supplied census has no issues, status is
`INTERNAL_CENSUS_ONLY_NOT_LIVE`, and the report explicitly keeps all of these
false: `expected_calendar_verified`, `server_receipt_clock_attested`,
`source_authenticated`, `provider_entitlement_verified`,
`retention_and_display_rights_verified`, `executable_bid_ask_verified`,
`live`, and `may_execute_order`. A failing census reports `REVIEW_REQUIRED`.

## Example: synthetic data only

```python
from app.prospective_receipt_census import audit_declared_m1_receipts

bar_start = 1790000040  # synthetic UTC minute start
receipt = {
    "provider": "fixture", "symbol": "XAU/USD", "venue": "synthetic",
    "price_side": "BID", "bar_start_utc": bar_start,
    "received_at_utc": bar_start + 65,
    "open": 100.0, "high": 102.0, "low": 99.0, "close": 101.0,
}
report = audit_declared_m1_receipts(
    [receipt], [bar_start], provider="fixture", symbol="XAU/USD",
    venue="synthetic", price_side="BID", observed_at_utc=bar_start + 90,
)
assert report["live"] is False and report["may_execute_order"] is False
```

Run the isolated tests with:

```sh
cd backend && PYTHONPATH=. pytest -q tests/test_prospective_receipt_census.py
```

## Activation blockers

Before an authenticated prospective feed can be advertised or used for any
forecasting, an owner-approved integration must independently verify: provider
instrument entitlement and display/non-display/retention rights; source and
venue identity; TLS-authenticated responses; receipt timestamps assigned by a
trusted server (with clock-skew monitoring); an independent versioned expected
session calendar and expected-bar population; bounded durable append-only
storage, deduplication, restart/replay tests, provider corrections, and real
freshness monitoring. BID historical bars are not broker executable quotes.
No CFD API support should be inferred from Trading 212's Invest/ISA API.

This helper does not establish any of those conditions. Historical archives
with unresolved collisions remain quarantined; production backup/restore,
rollback and post-deployment health gates remain mandatory for PR #65.
