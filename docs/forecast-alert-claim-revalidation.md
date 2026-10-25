# Forecast alert claim-time journal revalidation (Loop 5)

The disconnected forecast outbox previously validated its journal only when an
alert was **queued**. A later completed candle could void a 12-candle forecast
because of a missing intermediate bar, while its queued alert was still within
its age budget. The outbox could then claim that obsolete alert without
re-reading the forecast. This change fails closed at the **claim** boundary.

Before changing a `QUEUED` alert to `IN_FLIGHT_UNCERTAIN`, the server now
loads and validates the journal from the **same database transaction**. It
requires the exact source identity, still-`PENDING` forecast, and matching
forecast event sequence, model, horizon, base candle and issuance timestamp.
Missing or corrupt journals raise an error. A voided, settled or mismatched
forecast yields no claim, no claim audit event, and no delivery permission.
The outbox remains queued for explicit operator cancellation/reconciliation;
it is not silently marked delivered.

The journal row is read with `SELECT ... FOR UPDATE` on PostgreSQL, so its
read is ordered against concurrent forecast journal updates in that database
transaction. SQLite does not provide equivalent row-level locking; the
synthetic SQLite tests do **not** establish PostgreSQL race safety. A
settlement *after* the claim transaction commits can still occur before any
external sender runs. A future authenticated sender must recheck expiry,
source entitlement and completed-candle eligibility immediately before
sending, with durable provider receipts and crash-recovery tests. There is no
exactly-once delivery guarantee.

No sender, scheduler, endpoint, broker adapter, data feed, schema migration,
paid service, or order execution was added. The outbox's
`deliveryVerified=false`, `sourceAuthenticated=false`,
`notificationEnabled=false` and trading permissions remain unchanged.
No production dataset was touched. Run:

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_forecast_alert_claim_revalidation.py
```

## Loop 1 / operational handoff

Supply an entitled authenticated source of prospective completed candles,
provider receipt identity, server-owned receipt time, market-session closure
policy and real bid/ask observations where legally available. Run dedicated
PostgreSQL two-writer and process-kill acceptance tests for journal append
versus outbox claim, including crash recovery and notification-provider
idempotency/receipt reconciliation. Before production release, verify the
exact Render workspace, a **restored** backup, rollback and post-deployment
health. Historical BID candles are not executable quotes. Synthetic tests
do not demonstrate calibration, profitable returns or live alerts.
