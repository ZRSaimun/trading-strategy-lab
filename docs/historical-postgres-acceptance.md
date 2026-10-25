# Disposable PostgreSQL historical-import acceptance

This is a **synthetic-data-only** integration test for the review-stage,
source-isolated HistData importer and authenticated history API. It is not a
license check, proof of archive authenticity, live-feed activation, or permission
to use a historical dataset in trading.

The dedicated `historical-postgres-acceptance` GitHub Actions workflow starts a
temporary PostgreSQL 16 service and runs:

```bash
cd backend
TSL_PG_HISTORY_TEST_URL='postgresql+psycopg://postgres:postgres@127.0.0.1:5432/trading_lab_test' \
  PYTHONPATH=. pytest -q tests/test_history_postgres_acceptance.py
```

The test **refuses any non-loopback PostgreSQL host** and any database name
that does not end in `_test`. It creates a unique random
`history_accept_<uuid>` schema, installs only the isolated `historical_*`
tables there, and drops that schema during fixture teardown. **Never** point
`TSL_PG_HISTORY_TEST_URL` at production or a database containing user data.
The workflow runs only for pull requests changing historical import/API code,
the test itself, or its workflow; it has read-only repository permissions and
does not deploy.

The tests exercise:
- Clean synthetic M1 ZIP ingestion, PostgreSQL persisted rows, authenticated
  history inventory/candle retrieval, provenance and `HISTORICAL ONLY` labels.
- Duplicate/conflicting timestamps -> `QUARANTINED`, retained private evidence,
  and 404/empty history API visibility.
- Interrupted imports and missing stored checkpoint rows -> fail-closed
  quarantine, not research-ready.
- Source SHA-256 changes between initial and final verification -> `FAILED`,
  not exposed through the API.
- Previously `READY` imports with missing stored candles -> downgraded on
  explicit reimport verification.

Passing these tests **does not** certify production backup restoration, rollback,
health checks, source rights, fixed-EST convention, cross-archive gaps,
authenticity, full backtest validity, post-import tamper resistance, or
execution-quality bid/ask prices. It does not run against the owner's original
Gold, WTI or Nasdaq ZIPs. Their known conflicts remain quarantined.

This workflow is separate from the existing PostgreSQL **paper-risk** CI job;
neither job is a production acceptance test. Before any merge that could
auto-deploy, reconcile the branch with fresh `main`, review concurrent PRs,
and independently verify production restore/rollback and post-deploy health.
