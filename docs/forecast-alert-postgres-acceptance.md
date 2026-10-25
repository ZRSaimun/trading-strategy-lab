# Loop 5: PostgreSQL forecast alert outbox acceptance

This is a **disconnected test-only** gate for `ForecastAlertOutbox` and `ForecastEventStore`. It does not deliver notifications or connect to market feeds, brokers, paper accounts or production databases.

The opt-in test `backend/tests/test_forecast_alert_outbox_postgres.py` uses two independently pooled SQLAlchemy engines against a local disposable PostgreSQL database. It requires `FORECAST_ALERT_TEST_DATABASE_URL` with a PostgreSQL driver, host `localhost`, `127.0.0.1` or `db`, a database whose name begins `test_`, and no URL query parameters. It creates a randomized `test_forecast_alert_*` schema and drops only that schema on cleanup. Never supply real credentials or a production database. No secrets are committed; the CI password is scoped to its disposable container.

The dedicated GitHub Actions workflow `.github/workflows/forecast-alert-postgres.yml` provisions a local PostgreSQL 16 service and runs both the new outbox test and the existing cross-engine forecast-journal acceptance test. This prevents the PostgreSQL tests from silently remaining skipped in ordinary SQLite-only CI.

Acceptance checks:
1. Two workers read the same queued alert and race the compare-and-swap claim. Exactly one wins; only one claim audit is committed.
2. A separately connected/restarted worker observes the persisted uncertain claim and cannot automatically claim or queue it again.
3. Wrong-claim acknowledgments fail, while a matching self-attested ACK is persisted and explicitly remains **unverified delivery**.
4. An injected audit insert failure rolls back the claim state change. A later independent worker can safely claim the still-queued record.
5. The companion journal acceptance covers same-sequence competing writers and audit rollback.

**Limitations:** These are deterministic synthetic race and transaction-failure tests, not operating-system process-kill tests, authenticated external delivery receipts or proof of exactly-once delivery. Database administrators can still alter data and hashes. A claim is not a send, an ACK is not a provider receipt, and an uncertain claim requires reconciliation rather than automatic retry. Test green does not authorize a live notification sender, paper fills, broker orders, or deployment.

## Loop 1 handoff

Supply a legitimately licensed and authenticated completed-candle feed with provider/instrument/price-side identity, server-owned receipt timestamps, market-session and gap semantics, and explicit data-freshness thresholds. Independently verify delivery receipts before enabling real notifications. Keep historical BID research candles distinct from executable bid/ask quotes. Production release additionally needs current-main reconciliation, a proven backup/restore, rollback plan, healthy staging and post-deploy checks. Real-money orders always require separate owner confirmation per order and an eligible supported broker account.
