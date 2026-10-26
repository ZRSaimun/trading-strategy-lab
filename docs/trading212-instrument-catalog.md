# Trading 212 equity instrument catalog reconciliation (disconnected)

`app.trading212_instrument_catalog.reconcile_trading212_instrument_catalog`
accepts **two already-obtained, caller-supplied** responses from the opt-in
read-only Trading 212 adapter: `instruments` and `exchanges`. It validates
response declarations, joins each instrument's `workingScheduleId` to a
unique exchange `id`, checks the documented instrument type/currency/quantity
fields, and produces a stable SHA-256 fingerprint of selected instrument and
exchange schedule metadata. This helps identify *declared* accessible equity
instruments and catalog drift; it does **not** connect an account or request
market data. Unknown exchange references, duplicate tickers/IDs, mismatched
account type/environment, or receipts more than ten minutes apart fail closed.

The output contains aggregate counts and **only explicitly requested** ticker
metadata (up to 25 tickers). It does not copy private account summaries, raw
responses, credentials or arbitrary provider headers. The declared account
scope SHA-256 is required but **not returned or authenticated**. A matching
account type/environment and nearby local receipt times do **not** prove the
two requests used the same account, were not tampered with, or were fresh.
The catalog SHA-256 is a local deterministic digest, **not a provider
signature**; the source response digests are caller-supplied observations.
Exchange `workingSchedules` are fingerprinted but are **not** interpreted as
verified market calendars or trading sessions.

Official Trading 212 API documentation, checked **26 October 2026**:
https://docs.trading212.com/api/instruments/instruments
and https://docs.trading212.com/api . The API is beta and supports **Invest
and Stocks ISA only, not CFD accounts**. The metadata endpoint documents
`ticker`, `type`, `currencyCode`, `workingScheduleId`, and exchange `id` and
`workingSchedules`; metadata is refreshed periodically. This catalog is
**not a completed-candle feed, bid/ask quote source, instrument entitlement
certificate, permission to redistribute, or order-execution pathway**.

## Example (synthetic only; no broker request)

```python
from app.trading212_instrument_catalog import reconcile_trading212_instrument_catalog

# These are already obtained from separately authorized, budgeted GETs.
# Do not fetch in a loop: the Trading 212 provider limits apply per account.
report = reconcile_trading212_instrument_catalog(
    instruments_receipt, exchanges_receipt,
    declared_account_scope_sha256=owner_declared_scope_sha256,
    requested_tickers=["AAPL_US_EQ"],
)
assert report["market_data_feed"] is False
assert report["may_execute_order"] is False
```

Use `app.trading212_request_budget` only after owner-controlled provisioning
and entitlement/rights review. The broker's instrument metadata and exchanges
GETs must each be separately pre-reserved; **the existing 60-second local
pacing remains enforced**. This module never bypasses that control, retries,
logs keys, polls, persists records, or adds a website route. Treat ticker
matches as `DECLARED_EQUITY_METADATA_RECONCILED_UNVERIFIED`, never live CFD
market data or evidence of executable liquidity.

Offline synthetic tests:
`cd backend && PYTHONPATH=. pytest -q tests/test_trading212_instrument_catalog.py`

**Release gate:** PR #65 remains draft and undeployed until verified provider
account identity, permissions, market-data rights, independently validated
sessions and freshness, authenticated staging, private durable storage,
production backup restoration, rollback and health checks. No order or
production data path is activated by this change.
