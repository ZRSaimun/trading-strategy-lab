# Offline demo receipt journal: abrupt process termination regression

This is a **test-only**, opt-in research extension to
[the local declared demo receipt journal](offline-demo-receipt-sqlite-journal.md).
It adds no API route, broker connector, order sender, credentials, schema
migration, production data change, or application startup task.

## What is tested

`backend/tests/test_offline_demo_receipt_sqlite_process_recovery.py` runs an
independent Python process and deliberately terminates it via `os._exit`
at four SQLite transaction boundaries: after snapshot INSERT, after head
UPDATE, immediately before COMMIT, and immediately after COMMIT. It repeats
all four boundaries for genesis and for a second partial-fill snapshot.

After each termination, the parent reopens the actual SQLite file and
verifies full `PRAGMA integrity_check`, head/snapshot population,
revision/partial-fill exposure, compare-and-swap recovery, and retry
idempotency. A transaction killed before COMMIT must leave **no partial
journal revision**; a transaction killed after COMMIT must be visible
exactly once. The caller-declared broker completeness and execution
permissions remain false.

Run from `backend`:

```bash
PYTHONPATH=. pytest -q tests/test_offline_demo_receipt_sqlite_process_recovery.py
```

The tests use only synthetic XAUUSD-CFD order receipts and a temporary
local SQLite database. No licensed market archive, network connection,
actual broker order, external database, or real account is involved.

## Limits and release gate

These are **abrupt process-exit** tests, not physical power-failure,
kernel-panic, disk-write-cache or storage-device durability tests. They do
not verify restoration of an independent backup, recovery of a lost disk,
authenticated broker receipt population, true exchange queue priority,
executable spreads, CFD financing, FX settlement or profitable backtests.
SQLite WAL/FULL-synchronous behaviour still depends on the filesystem
and storage stack. Hashes are not signatures.

A successful process-recovery test is not permission to deploy or execute.
Keep production changes gated on confirmed service/workspace, restorable
backup, rollback and independent HTTP health checks. For broker-linked
research, reconcile every receipt and open exposure against independently
authenticated read-only broker evidence before trusting it.
