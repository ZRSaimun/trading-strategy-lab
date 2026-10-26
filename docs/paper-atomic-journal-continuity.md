# Atomic paper quote + journal continuity gate (Loop 4)

## Scope

The opt-in `AtomicPaperQuoteJournalStore.checkpoint()` now checks append-only
paper journal history against the **server-loaded** previous journal envelope
before advancing the quote replay marker, journal checkpoint or audit event.
It reuses `review_paper_journal_continuity()` from the existing read-only
preflight. A rejected transition returns `HOLD_RECONCILIATION` with reason
`JOURNAL_HISTORY_CONTINUITY_FAILED`; it commits neither marker nor audit.

The checks reject rewritten or removed actions/events, missing/reordered/
duplicate/malformed order IDs, and revisions with no newly appended action.
Updates to derived order status remain possible. The existing full-value
conditional journal UPDATE and quote-marker compare-and-swap arbitrate races.
Initial checkpoints have no predecessor; they still require independent replay
verification before anyone can trust paper orders or fills.

## Verification

Run `cd backend && PYTHONPATH=. pytest -q tests/test_paper_quote_journal_atomic.py`
and the complete backend, frontend and CI suites. Synthetic SQLite regression
cases exercise denial without partial writes and a valid cumulative update.
Disposable PostgreSQL multi-writer and abrupt-process-crash acceptance must
still be run and reviewed before any operational use.

## Explicit safety limitations

- This is a disconnected, **unverified** paper-state writer, not an order gate.
- Inputs are not authenticated broker quotes or verified fills.
- SHA-256 and database CAS are integrity/concurrency checks, not authentication.
- No broker connection, API route, secret, schema migration or live order exists.
- The existing TypeScript replay journal must independently replay all actions.
- No automatic paper execution or real-money execution is authorized.
- A broker's confirmed positions, stops, funding and daily-loss state still need
  transactional reconciliation with risk reservations (draft PR #26).
- Keep stacked work on draft PR #127 until that branch is reviewed/merged.
- Do not deploy until actual Render auto-deploy settings, restorable backup,
  rollback and post-deploy health verification are independently established.

Trading 212's documented Public API supports Invest and Stocks ISA accounts,
not CFD accounts; do not claim CFD execution support.
