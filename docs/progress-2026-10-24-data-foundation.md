# Data foundation follow-up — 24 October 2026

## Research and implementation

Reviewed official HistData format specification: https://www.histdata.com/f-a-q/data-files-detailed-specification/ . ASCII and MetaTrader M1 formats contain bid OHLC and use fixed EST without DST. The validator now accepts explicit `--format mt`, identifies bid quotes and tests summer conversion with UTC-5. User archives still unavailable; documentation does not authenticate a particular archive or prove rights.

Replaced chart endpoint full-history `.all()` with SQLAlchemy batched descending iteration and incremental OHLC aggregation. It retains at most 2,000 aggregate buckets plus current bucket; stops upon observing the next bucket and closes the result cursor. Cursor filtering excludes the entire boundary bucket to prevent partial OHLC. Volume remains unknown when any contributing row lacks volume. Existing response shape remains unchanged. This reduces application memory; it is not preaggregation and a monthly page can still read millions of rows. Production PostgreSQL latency is unmeasured.

Affected files: backend/app/main.py, backend/app/market.py, backend/app/archive_validation.py; three test files (including new test_chart_pagination.py); validator docs and this report.

## Verification

52 backend tests passed, including pagination across an API dataset, aggregation equivalence, early iteration termination, weekly/monthly buckets, missing volume and MT summer timestamp conversion. `git diff --check` passed. Tests use synthetic fixtures and SQLite; PostgreSQL server-cursor behavior and query plans still need integration checks. Frontend unchanged in this follow-up; earlier 42 frontend tests and typecheck passed, earlier production build failed with uv_resident_set_memory runtime error.

No production import, real-data backtest, model training, forecast or profitability experiment ran. No deployment or production migration performed; no paid services purchased. Existing replacement importer remains unchanged and must not be used for cumulative backfill. No source/dataset schema migration yet.

## Execution order and required resources

1. Provider/dataset-aware storage: define exact instrument, venue, provider, quote side, timezone convention, immutable archive hash and collision policy. Build and test migrations locally; review before production changes.
2. Resumable append importer: transactional chunks, durable checkpoints/quarantine, exact duplicate idempotency, conflict rejection, cancellation and restart tests. Avoid switching the existing UI to unsafe partial append semantics.
3. Attach original historical ZIP files in this conversation. This enables real manifest generation, format/quality validation and throughput tests. Filenames alone do not provide file access. Do not relabel NSXUSD as NDX cash or NQ futures.
4. Connect the Trading Strategy Lab Supabase project through scoped authorization. The currently listed project is unrelated and was not inspected. This enables schema/row inventory and production-backed integrity checks. Never paste credentials into chat.
5. Supply Render project access through a scoped connection for deployment logs, configuration and rollback verification. Public health HTTP success is insufficient for authenticated acceptance.
6. Recover prior backtest configurations/results alongside immutable input archives. Reproduce A–E before model selection, then add cost sensitivity, protected chronological holdouts and probability calibration against simple baselines.

No new paid service is required for the next local implementation steps. Licensed execution-quality spreads/quotes may be required later; bid-only archives cannot establish actual historical bid/ask costs.
