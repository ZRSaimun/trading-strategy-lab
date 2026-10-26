# Trading 212 equity instrument catalog drift (offline, disconnected)

`app.trading212_catalog_drift.compare_trading212_catalogs` compares two
**already obtained** pairs of Trading 212 Invest/Stocks ISA instrument and
exchange metadata receipts. It calls the existing strict catalog reconciler
for **both** snapshots before comparing. No HTTP request, account login,
market-data subscription, persistence, polling or order path is involved.

The report counts additions/removals from the **declared accessible catalog**,
changes to shared ticker metadata (type, currency, exchange/schedule ID, names,
extended-hours flag, maximum quantity), and any canonical catalog fingerprint
change. A changed fingerprint with no changed ticker fields may indicate
exchange name or schedule changes. Instrument list order alone does not cause
drift. Only up to 25 **explicitly requested** tickers appear in the report;
no full instrument population or private account data is emitted.

Both receipt pairs must pass the prior catalog checks and declare the same
environment and account type. Their **local UTC receipt windows** must be
strictly ordered and non-overlapping. This does **not** authenticate timestamps,
prove a shared account, certify provider entitlements, establish trading
hours, or establish why an instrument appeared/disappeared. Catalog digest
changes are not signed by Trading 212. The output always denies CFD support,
live market-data status, source authenticity, order execution and permission
to trade. Do not interpret additions as guaranteed tradability, removals as
delistings, or metadata as executable bid/ask quotes.

Official provider documentation, reviewed **26 October 2026**:
https://docs.trading212.com/api and
https://docs.trading212.com/api/instruments/instruments .
The public API is currently documented for **Invest and Stocks ISA only,
not CFD accounts**. Instruments and exchanges metadata are refreshed
periodically and are not a completed-candle feed. API limits apply per
account, across keys/IP addresses. Obtain any receipts only through an
owner-approved read-only workflow with the separate durable request budget
and independently verified data rights.

## Synthetic example (no broker connection)

```python
from app.trading212_catalog_drift import compare_trading212_catalogs

report = compare_trading212_catalogs(
    previous_instruments_receipt, previous_exchanges_receipt,
    current_instruments_receipt, current_exchanges_receipt,
    declared_account_scope_sha256=owner_declared_scope_sha256,
    requested_tickers=["AAPL_US_EQ"],
)
assert report["market_data_feed"] is False
assert report["may_execute_order"] is False
```

Offline tests:
`cd backend && PYTHONPATH=. pytest -q tests/test_trading212_catalog_drift.py`.

**Release gate:** This is an isolated review utility on draft PR #65, not a
production activation. Authenticated owner-controlled staging, independent
account and data-rights verification, durable private storage, backup restore,
rollback and health checks remain necessary before merging or deploying.
