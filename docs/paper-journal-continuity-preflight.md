# Loop 4: Paper journal history continuity preflight (26 October 2026)

`app.paper_journal_continuity_preflight.review_paper_journal_continuity` is an **offline, read-only diagnostic** for comparing two versioned PAPER checkpoint JSON snapshots. It never writes to a database, creates a brokerage request, releases a risk reservation, or authorizes any paper/live order.

The evaluator rejects malformed or oversized checkpoint JSON and invalid revisions. For valid inputs it checks that revisions are consecutive, source identity is unchanged, the previous action and event arrays are exact prefixes of the new arrays, at least one action was appended, and the original order IDs remain in their original order without duplicate/malformed IDs. An existing order's status may legitimately change as a simulated fill progresses; the reviewer deliberately does not require full order-object equality.

Example:

```python
from app.paper_journal_continuity_preflight import review_paper_journal_continuity

result = review_paper_journal_continuity(
    prior_checkpoint_json, proposed_checkpoint_json,
    expected_revision=7, next_revision=8,
)
assert result["status"] == "HOLD_RECONCILIATION"
assert result["may_execute_paper_order"] is False
assert result["may_execute_real_order"] is False
```

`assumption_checks_pass` only describes internal consistency of **caller-supplied, unauthenticated** snapshots. It is never permission to trade. The SHA-256 review fingerprint is not a signature. This evaluator does **not** independently replay actions, authenticate broker fills, prove quote freshness, verify stop coverage, or guarantee persistence. In particular, it cannot detect history tampering when both the previous and proposed snapshots are replaced consistently.

**Next integration:** obtain the prior checkpoint from the server-owned transactional store, perform the continuity comparison **inside the same PostgreSQL transaction** as the quote-marker and journal compare-and-swap, independently replay the resulting checkpoint using the TypeScript `PaperReplayJournal.restore()` contract, and fail closed on any disagreement. Do not run a separate preflight read followed by an unguarded write: that introduces a time-of-check/time-of-use race. Do not retroactively apply this policy to older synthetic fixtures without testing expected append-only behavior.

Verification: `cd backend && PYTHONPATH=. pytest -q tests/test_paper_journal_continuity_preflight.py`. Full CI, PostgreSQL concurrency, abrupt-process-crash recovery, Render production backup/rollback and authenticated broker evidence remain separate release gates.

Trading 212's documented Public API is for Invest/Stocks ISA, not CFD order execution. No live connector, credentials, paid service, or market-profitability claim is introduced.
