# Offline declared M1 receipt SQLite checkpoint journal

The opt-in module backend/app/declared_m1_receipt_sqlite_journal.py persists
**caller-declared** completed-minute receipts and a frozen operator calendar.
It is not connected to the API, a provider, scheduler, or trading engine.
Nothing in this journal can mark prices live or authorize an order.

## API

- append_declared_m1_checkpoint(db_path, receipts, manifest, expected_previous_checkpoint_sha256)
- read_declared_m1_checkpoint_head(db_path, manifest)

Use a locally controlled durable SQLite file and an already compiled
ExpectedM1Manifest. The first expected previous checkpoint is exactly
64 zero characters; each subsequent append requires the previously returned
checkpoint_sha256. An identical retry with its original previous hash is
idempotent. Concurrent or stale writers fail closed. See synthetic fixtures
in backend/tests/test_declared_m1_receipt_sqlite_journal.py.

## Guarantees and limits

- A SQLite BEGIN IMMEDIATE transaction, WAL, synchronous=FULL, a
  compare-and-swap head and numbered snapshots protect ordinary
  process crashes and racing writers on a suitable local filesystem.
- Every read and append checks SQLite integrity, retained snapshot hashes
  and chronology, each compiled calendar fingerprint and the existing M1
  receipt census/continuity audit. Missing rows, changed OHLC, rewritten
  receipt times, retrospective calendar declarations and stale snapshots
  are refused. Maximum 16 snapshots per source/calendar scope and 4 MB
  per canonical JSON snapshot; no silent compaction or deletion.
- The returned report contains only counts, checkpoint digests and
  declarations; **stored SQLite payloads contain prices and receipt times**.
  Secure the database and its backups. Do not expose it through an
  unauthenticated route or commit it to Git.
- The hash chain is **not an external trust anchor**. Anyone able to replace
  the entire database and all checkpoints can forge history. Persist and
  compare head hashes in a separately controlled immutable store, test
  backup restoration, and verify recovery/rollback before production use.
- Source authenticity, provider entitlements, retention/display rights,
  independent market calendars, UTC clock integrity, venue/price-side
  semantics, executable spreads and freshness remain unverified. All data
  are **offline declared evidence**, never an authenticated feed.
- No background polling, vendor requests, subscriptions, production database
  changes, credential handling, or broker orders are performed. This module
  does not migrate existing datasets and is not activated in the website.

## Synthetic test command

    cd backend
    PYTHONPATH=. pytest -q tests/test_declared_m1_receipt_sqlite_journal.py

Keep draft PR #65 unmerged and undeployed until exact-head CI, independent
data-rights verification, authenticated provider acceptance, durable storage
and external anchors, backup restore, rollback rehearsal and health checks.
