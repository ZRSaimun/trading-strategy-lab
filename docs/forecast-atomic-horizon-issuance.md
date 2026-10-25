# Loop 5 — atomic multi-horizon forecast issuance

This disconnected research change adds `ForecastEventStore.append_forecasts_atomic` and updates `CausalForecastIssuer` to issue eligible 1-, 3- and 12-candle forecasts in one transactional compare-and-swap with one audit row per event. It validates exact feed/lag identity, the latest persisted completed candle, identical model/base, distinct horizons, strict issuance deadline, replay integrity, sequence and size bounds. Stale CAS and interrupted audit writes cannot persist a partial group.

**Important limit:** the candle and forecast batch are still separate transactions. If interrupted after candle persistence, retry before the issuance deadline can fill missing horizons, but late recovery fails closed. Old partially issued groups are not rewritten. A checksum in mutable database storage is not tamper-proof external evidence. This remains `UNAUTHENTICATED_DISCONNECTED_RESEARCH` with no live feed, notification transport, paper fill, broker adapter, executable quote or real order.

Test: `cd backend && PYTHONPATH=. pytest -q tests/test_forecast_atomic_batch.py tests/test_forecast_causal_issuer.py tests/test_forecast_event_store.py`. Synthetic SQLite tests exercise all-or-none audit rollback, stale CAS, source/clock validation, 1/3/12 issuance and idempotent retries; they are not market-performance evidence. The optional isolated PostgreSQL concurrency/crash acceptance remains a separate prerequisite.

**Loop 1 handoff:** licensed authenticated completed-candle source, trusted server receipt timestamps, market-session/gap rules, transactional durable outbox and independently verifiable alert receipts, isolated PostgreSQL multi-worker process-kill/recovery tests, and genuine independently sourced bid/ask quotes before any forward demo P&L. Historical BID candles are not executable quotes. Live orders require documented eligible broker/account, limits, current executable quote and explicit owner confirmation for each order.

Keep PR #27 draft/unmerged and production untouched until reconciliation with current main, exact-head green CI, independently verified restorable backup, rollback and post-release health.
