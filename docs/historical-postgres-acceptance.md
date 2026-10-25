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

## Disposable PostgreSQL dump, restore and rollback drill (25 October 2026)

The historical acceptance suite additionally creates two synthetic source
archives (one clean, one with a conflicting timestamp) in a unique isolated
PostgreSQL schema. It takes a real custom-format `pg_dump` of that schema,
restores it using `pg_restore` into a **new random `*_test` database** on
loopback, and verifies the exact dataset, candle and quarantine rows. The
authenticated API must show only the clean historical archive, return 404 for
the quarantined archive and reject an unauthenticated inventory request.

The test then deliberately alters **only the disposable restored database**,
confirms the historical API no longer exposes the modified READY dataset, and
restores the original dump with `--clean --if-exists --single-transaction`.
It checks byte-for-byte-equivalent SQL row values and READY visibility after
this rollback. The temporary database is dropped in teardown. The source
fixture requires a loopback PostgreSQL URL whose database ends in `_test`;
a separate randomly named restore database also ends in `_test`. The dump
lives in a temporary directory, has mode 0600, and is never committed.

This drill requires local `pg_dump` and `pg_restore` executables compatible
with the disposable PostgreSQL server. It fails rather than silently skipping
if they are missing. The CI job runs with read-only GitHub permissions and
synthetic prices only.

**Scope boundary:** This validates isolated historical-table backup/restore
and rollback logic, not a production database recovery, full application
schema migration, Render/Supabase disaster recovery, restored session/AI-token
invalidation, actual archive licensing, or HTTPS health after deployment.
Production merge/deploy remains blocked until independent owner-environment
backup, restore, rollback, authentication and health checks succeed.
