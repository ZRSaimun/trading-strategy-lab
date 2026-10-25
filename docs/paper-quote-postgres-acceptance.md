# Disposable PostgreSQL acceptance for quote replay markers

This is a **disconnected, synthetic safety test** for `backend/app/paper_quote_replay_store.py` on draft PR #45. It is not broker authentication, a stop-loss order, a trade execution service, or approval to merge/deploy.

The new `backend/tests/test_paper_quote_replay_postgres.py` suite checks three PostgreSQL properties:

1. Two simultaneous first writers observing the same quote cannot both insert an accepted marker or duplicate its audit.
2. Two simultaneous updates reading the same prior revision cannot both advance the marker; one writer is held for reconciliation.
3. If an audit insert fails, the record insert/update rolls back; retry after recovery advances exactly once.

The suite runs with a **disposable PostgreSQL 16 service** in `.github/workflows/quote-replay-postgres.yml`. It creates a random `quote_accept_*` schema and drops only that schema. Its environment URL must point to a loopback PostgreSQL database ending in `_test` and must not contain query parameters. Never supply a production URL or real broker credentials.

Local optional execution (only against a disposable loopback database):

```sh
cd backend
TSL_PG_QUOTE_TEST_URL='postgresql+psycopg://test_user:test_password@127.0.0.1:5432/tsl_quote_test' PYTHONPATH=. python -m pytest -q tests/test_paper_quote_replay_postgres.py
```

Without `TSL_PG_QUOTE_TEST_URL`, tests skip. This acceptance is independent of SQLite regressions, which do not prove PostgreSQL concurrency.

**Release gate:** Require exact-head green CI for all foundation jobs and the PostgreSQL job, independent review, and atomic coordination with risk reservations (#26), daily-loss breaker (#39), duplicate-order quarantine (#40), broker snapshots (#42), and the paper journal. Authenticated quotes, durable rejected-event audit, server-clock trust, human-specific live-order consent, and production backup/rollback/health verification remain missing. Keep PR #45 draft/unmerged/undeployed. No real or demo orders, secrets, subscriptions or production datasets are touched.
