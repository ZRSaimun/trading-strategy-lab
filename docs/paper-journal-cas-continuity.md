# Standalone paper journal CAS history-continuity gate

This change wires the existing `review_paper_journal_continuity` preflight into the
**standalone** `PaperJournalStore.compare_and_swap` update transaction.

On a revision update, the store loads the previous checkpoint from the database,
checks that the proposed revision is consecutive, actions and events preserve
their historical prefix, a new action was appended, and order identifiers remain
valid, unique and in their original order. Derived order status changes are
allowed because orders can evolve when new paper actions are replayed.

If the checks fail, the update raises `ValueError`. No checkpoint or success
audit is committed. The full stored-value compare-and-swap still arbitrates
concurrent writers; a successful check against a stale row is not sufficient to
overwrite another writer. Initial revision 0 is not covered by a predecessor
comparison; it still requires the existing schema and size checks.

## Boundaries

- This is **paper-only**, with no API route, broker connection, order sender,
  credential handling, paid service, database migration or live-trading path.
- It does **not** authenticate checkpoints or independently replay TypeScript
  `PaperReplayJournal.restore()` actions. A malicious writer able to forge an
  entire new checkpoint could still produce plausible append-only history.
- **Important:** `AtomicPaperQuoteJournalStore.checkpoint` is a *separate*
  writer and does not yet invoke this history gate. Do not treat its accepted
  unverified checkpoints as covered by this change. The atomic path requires a
  compatible cumulative-history fixture and transaction-level integration.
- The standalone CAS rejects snapshot-only revisions without a new action. Such
  clients must adapt to an explicit append-only action history, not weaken the
  gate. No historical checkpoint is migrated or rewritten automatically.
- SHA-256 diagnostics are not signatures, order confirmations or approvals.
  An actual broker fill, stop acknowledgement or balance must be verified
  against authenticated provider evidence separately.
- SQLite regression tests exercise history preservation and audit immutability;
  PostgreSQL concurrent-writer and process-crash acceptance is still required
  before operational reliance. Existing PostgreSQL tests do not prove this
  newly wired history gate under all concurrent interleavings.

## Verification

Run `PYTHONPATH=backend pytest -q backend/tests/test_paper_journal_cas_continuity.py`
and the repository's full CI. No production deployment until the actual
Render service, restorable backup, rollback path and health check are verified.

## Next handoff

Wire a compatible history-continuity check into the atomic quote+journal writer
in the *same* database transaction, with deterministic replay validation,
authenticated quote provenance, crash-recovery and PostgreSQL concurrency
tests. Do not merge into a deployment-triggering branch until release gates
are independently verified. Live orders always require separate per-order
positive owner confirmation and secure supported-provider credentials.
