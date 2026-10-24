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
