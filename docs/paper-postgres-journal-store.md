# Atomic paper-journal checkpoint persistence (experimental)

`backend/app/paper_journal_store.py` implements an opt-in, transactional checkpoint store using the existing `records` and `audit` tables. It accepts a versioned JSON checkpoint from `frontend/lib/paper-replay-journal.ts`, enforces exact source identity and a bounded size, and persists an atomic revision compare-and-swap (CAS). It records only a session-ID hash, revision and checkpoint digest in the audit trail, not order details or credentials.

The first writer inserts under a unique primary key. Subsequent writers conditionally update the row only if the **entire previous record value** still matches, preventing stale writers from silently overwriting an intervening revision under PostgreSQL READ COMMITTED semantics. If a competing update wins, the method returns `False` and the caller **must reload**. All successful writes and their audit rows commit in one transaction; a failed write rolls back. Checkpoints survive process restarts on a persistent database. The store does not automatically create tables or alter a running service.

**Important: not live or ready for production activation.** No HTTP API route or UI is wired, no live broker or provider is contacted, no order is placed, and no production database is modified by this change. The server validates the envelope, revision, source identity, byte limit and SHA-256, but **does not replay the TypeScript trading rules**. A caller must run `PaperReplayJournal.restore()` before using stored order states; neither the SHA-256 nor deterministic replay authenticates maliciously rewritten market data. The same source identity must be verified against an authenticated quote provider before demo comparison. Hashes here detect accidental corruption, not malicious tampering.

The store currently writes a full bounded checkpoint per accepted event. This is intentionally a simple prototype; at 50,000 events or 8 MB it becomes inefficient. Before private deployment, add owner-authenticated API routes, rate limits, a PostgreSQL two-connection/kill-and-restart integration test, encrypted backups and restore drills, append-only authenticated event provenance, and compaction without destroying the audit chain. Review database quotas and latency; do not run this on a free production database without a retention and capacity plan. The optional SQLite test suite is **not evidence of PostgreSQL crash safety**.

Local regression checks from `backend`:

```sh
PYTHONPATH=. pytest -q tests/test_paper_journal_store.py
```

The synthetic tests exercise restart, revision conflicts, transaction interruption, identity isolation, corruption detection, size bounds and audit-only-on-success. They do not measure trading profitability or real broker fills.


## Optional local PostgreSQL concurrency and rollback acceptance test

The isolated `backend/tests/test_paper_journal_postgres.py` test requires a **separate local PostgreSQL test database** with a name beginning `test_`, e.g. `test_paper`. It rejects non-local hosts, database names without that prefix, and URL query parameters. Do **not** point it at production or reuse production credentials. It creates a randomized temporary schema, exercises the store using two independent database connections, and drops only that test schema. It never places orders or accesses provider data.

```sh
cd backend
# Provision a dedicated local test_paper database with a test-only PostgreSQL user first.
PAPER_JOURNAL_TEST_DATABASE_URL='postgresql+psycopg://TEST_USER:TEST_PASSWORD@127.0.0.1:5432/test_paper' \
  PYTHONPATH=. python -m pytest -q tests/test_paper_journal_postgres.py
```

The test synchronizes two competing writers after their reads and asserts **exactly one** revision-1 winner, a single stored session and the correct audit count. It then injects a failure during audit insertion and asserts that both the checkpoint update and audit are rolled back, followed by a successful retry and restart-load. Without the explicit test URL, pytest marks the test **SKIPPED**; a green CI run with that skip is **not** evidence of PostgreSQL concurrency or crash recovery. This is a transaction interruption simulation, not a real process-kill, power-loss, replica-failover or backup/restore test. Full durability and deployment readiness remain unverified.

The JSON envelope parser now also rejects duplicate object keys at any depth and non-finite numeric exponent overflow (e.g. `1e999`), rather than accepting ambiguous or non-replayable saved paper events. The Python store still does not certify order events against the TypeScript replay engine or authenticate market-data provenance.
