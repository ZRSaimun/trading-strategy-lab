# Offline declared demo receipt SQLite journal (Loop 3)

This is an **opt-in local research library**, not a broker adapter, API route,
background worker, production migration, live trading switch or executable
account reconciliation. It stores **caller-declared** demo receipt snapshots.
The caller must provide a complete valid order scope, receipt sequence and
manifest accepted by `offline_demo_order_receipt_replay`.

## API

```python
from app.offline_demo_receipt_sqlite_journal import (
    append_declared_demo_receipt_snapshot,
    read_declared_demo_receipt_journal_head,
)

genesis = "0" * 64
first = append_declared_demo_receipt_snapshot(
    "/private/local/declared-demo-receipts.sqlite",
    first_scope, first_events, first_manifest, genesis,
)
# Persist first["checkpoint_sha256"] separately for subsequent CAS writes.
second = append_declared_demo_receipt_snapshot(
    "/private/local/declared-demo-receipts.sqlite",
    later_scope, later_events, later_manifest,
    first["checkpoint_sha256"],
)
head = read_declared_demo_receipt_journal_head(
    "/private/local/declared-demo-receipts.sqlite", later_scope,
)
```

All fields are caller-supplied; no broker connection, login, credentials, order
submission, or external data access is implemented.

## Properties and limits

- SQLite `BEGIN IMMEDIATE` compare-and-swap, WAL and `synchronous=FULL`.
  Concurrent writers presenting the same prior checkpoint cannot both commit
  different snapshots. An exact retry of the most recent payload and its prior
  checkpoint is idempotent.
- Each append replays the proposed receipt manifest and validates **all**
  existing snapshots, SHA-256 links, revision sequence, declared receipt
  chronology and prior-to-current prefix continuity. Missing, rewritten or
  late-backfilled receipts fail closed. Reads revalidate the same chain.
- The local journal caps snapshots at **128 per order** and canonical JSON
  payloads at **1,000,000 bytes each**. It does not cap total order count or
  disk consumption; operators must apply local storage quotas and backups.
- Reads open SQLite in read-only mode. No deletion, archive publication or
  schema migration of the application database occurs.
- SQLite transaction durability depends on the filesystem, hardware and
  backup policy. A checksum is **not** a cryptographic signature or a trusted
  timestamp. An attacker controlling the SQLite file can recompute every
  digest; external broker receipts and independent checkpoints are required.
- A valid local chain does **not** prove complete actual fills, correct
  financing, CFD settlement, queue position, executable quotes, profitability
  or zero exposure after a cancel. Partial fills remain exposure until an
  independently verified broker reconciliation.
- `may_execute_demo_order` and `may_execute_real_order` always remain
  **false**. There is no Trading 212 CFD write integration.

## Recovery / rollback

For research-only use, stop writers, preserve the SQLite file and associated
`-wal`/`-shm` files, and restore a **verified, transactionally consistent**
backup. Do not manually edit rows, truncate receipt histories, reset CAS heads,
or treat a reconstructed checkpoint as independent evidence. If any checksum,
prefix, manifest or integrity check fails, quarantine the journal and reconcile
against independently authenticated read-only broker records before continuing.
Do not use this module for real-money order placement.

## Verification and next research

Synthetic tests cover restart, exact retries, stale concurrent CAS writers,
tampered local rows, missing revisions, rewritten receipts, backfills, invalid
inputs, separate order identities and randomized partial-fill partitions.
These tests validate invariants, **not** broker authenticity or strategy edge.

Next: signed/independently retained checkpoint evidence, authenticated
read-only demo-broker receipts, external account-position reconciliation,
point-in-time executable quote/fee evidence and frozen multi-year net-of-cost
walk-forward holdouts. No broker is declared supported for live execution.
