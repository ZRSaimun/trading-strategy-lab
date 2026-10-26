# Loop 4: bounded paper-journal payload parsing

This change hardens the existing disconnected `PaperJournalStore` checkpoint parser.
It introduces no HTTP endpoint, broker connection, order sender, credentials,
database migration, background worker, or change to owner data.

## Safety invariants

- Checkpoint `version` must be the **exact integer** `1`. JSON `true`,
  `1.0`, `"1"`, null and unsupported versions fail closed.
- Each of `actions`, `orders` and `events` is a list of at most 50,000
  entries. Previously only `actions` was capped.
- Stored record envelopes are bounded to **8,004,096 UTF-8 bytes before JSON
  parsing**. This accommodates the 8,000,000-byte checkpoint and its
  metadata; corrupted/oversized records require manual recovery.
- A rejected write never publishes a checkpoint or a successful audit event.
  A rejected load or CAS does not silently overwrite an existing record.
- These bounds do **not** validate event semantics, authenticate a quote,
  prove a stop fill, or authorize any paper/live order.

## Tests and integration

Run `cd backend && PYTHONPATH=. pytest -q
tests/test_paper_journal_store.py tests/test_paper_journal_payload_bounds.py`.
The new SQLite regression tests cover exact-version validation, all three
collection bounds, the inclusive boundary, a corrupted oversized stored
envelope, and a forged stored checkpoint with a recomputed SHA-256.

Before operational use, connect authenticated broker inventory and quote
provenance, persist order-intent reservations with PostgreSQL transactional
concurrency checks, reconcile fills/stops, verify backup restoration and
rollback, and retain per-order explicit owner approval for any real-money
submission. A checksum detects accidental corruption, not a malicious
rewrite. Trading 212's documented public API is for Invest/Stocks ISA, not
CFD accounts (official reference: https://docs.trading212.com/api).

The repository's Render blueprint currently declares
`autoDeployTrigger: checksPass`; do not merge or deploy this branch until
the actual service's deployment behavior and recovery procedure are verified.
