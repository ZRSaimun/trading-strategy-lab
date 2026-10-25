# Loop 5 — forecast journal independent-engine acceptance

This additive test checks the disconnected `ForecastEventStore` in `backend/app/forecast_event_store.py`. It introduces **no route, worker, migration, market feed, notification sender, paper fill, broker access, or order execution**. The input prices are synthetic, not provider candles or executable quotes.

## Verification

```bash
cd backend
PYTHONPATH=. pytest -q tests/test_forecast_event_store_cross_engine.py
```

The normal-CI SQLite test creates **two distinct SQLAlchemy engines** pointed at one disposable `tmp_path` database. It verifies cross-engine restart/load, stale expected-sequence rejection, no extra audit row after a rejected append, an injected audit-insert exception rolling back the candle, and successful recovery/settlement from the other engine. It is not a multi-process PostgreSQL test.

The PostgreSQL test is **opt-in**. Set `FORECAST_JOURNAL_TEST_DATABASE_URL` to a disposable, local `test_` PostgreSQL database (loopback or local Docker `db` host), then run the same command. The test refuses non-PostgreSQL, non-local, non-`test_`, and parameterized database URLs. It creates a unique `test_forecast_<random>` schema, scopes each transaction's search path and timeout, and drops only that schema. Two **independent engines** concurrently attempt the same expected-sequence append after synchronized reads: exactly one must win, with one audit row for the winner. It then injects an audit-insert failure, verifies rollback and no phantom settlement, retries from a fresh store at the correct completed-candle clock, and verifies recovery from the second engine. Never supply a production connection string. Keep the database isolated and disposable; this test creates and drops schema objects.

**Important:** If the PostgreSQL environment variable is absent, pytest **skips** that integration case. A green CI run with this skip is *not* PostgreSQL concurrency acceptance. A simulated audit failure is not proof of process-kill, disk-loss, PITR, restore, or production failover safety.

## Evidence and release gate

No prospective data authenticity, source entitlement, forecast accuracy, alert delivery, broker bid/ask, paper P&L, financing, slippage, maximum drawdown or trading edge is established by these tests. The forecast journal is an unsigned, mutable DB snapshot with a self-contained digest; an operator with DB write access can replace both data and digest. Source timestamps remain caller-controlled unless a future authenticated server-side worker binds receipt time. Keep `UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL` classification.

PR #27 must remain draft until reconciliation against current `main`, exact-head full CI, a successful opt-in isolated PostgreSQL acceptance, owner-verified restorable backup, rollback rehearsal, and post-deploy health checks. Do not deploy this research component merely because normal CI is green. Never label historical BID candles as live executable quotes.

## Loop 1 handoff

Provide entitled, authenticated completed-candle observations with source/venue/side identity, provider documentation, trustworthy server receipt timestamps, explicit session-aware gap policy, and independently auditable provider/transport receipts. Define safe retention and crash recovery for the forecast event journal, run opt-in PostgreSQL concurrency tests and genuine restart/restore exercises, and provide a durable transactional outbox with independently verifiable alert acknowledgements. Only then can an owner-authenticated prospective worker, reliable completed-candle alerts and a separately reconciled bid/ask paper ledger be enabled. Real-money orders always require a supported eligible broker, current executable quote, risk limits, and explicit owner confirmation **for each order**.
