# One-statement forecast journal/outbox reconciliation (offline)

`app.forecast_alert_atomic_snapshot.audit_persisted_forecast_alerts` is a
**disconnected, read-only** audit of persisted forecast events and alert states.
It runs exactly one bounded SQL `SELECT` to read the requested journal keys
and *all* `forecast-alert:` keys, then verifies envelopes, replays forecasts,
and reconciles every declared alert against its issuance event. An undeclared
persisted alert, missing journal/alert, duplicate declared identity, corrupt
payload, conflicting forecast metadata, >2,000 rows or >16 MB of returned
record contents rejects the entire audit. The session and expected-alert
inventory is still supplied by the caller and is not independently attested.

Example (in a **private, read-only, quiescent staging database**):

```python
from app.forecast_alert_atomic_snapshot import audit_persisted_forecast_alerts
report = audit_persisted_forecast_alerts(
    ["registered_session"], [("registered_session", "registered_forecast")],
    as_of=trusted_server_epoch_seconds,
)
```

The `session_factory` is injectable for isolated synthetic tests. In
PostgreSQL READ COMMITTED, a single SELECT observes one statement-level
snapshot, avoiding cross-query torn reads; this does **not** freeze the
underlying database after the SELECT, prove independent inventory completeness,
validate provider licensing or source authenticity, or prove provider/device
notification delivery. All notification and paper/live execution permissions
remain false. It does not issue `FOR UPDATE`, writes, external HTTP requests,
or broker orders. Do not expose its raw inputs or results to unauthorized clients.

This audit is not wired into any route, worker or scheduler. Do not deploy or
activate alert sends without authenticated entitled prospective completed-candle
receipts, verified session-aware expected-bar inventory, recipient opt-in,
transactionally durable claims and independently reconciled provider receipts.
A historical BID candle is not a live executable BID/ASK quote. Production
backup restoration, rollback rehearsal, exact-head CI and health checks remain
separate release gates. Synthetic regression tests cannot establish actual
forward accuracy, returns, drawdown or profitability.
