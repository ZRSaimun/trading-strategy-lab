# Loop 4 — disconnected market-session and quote continuity review

`backend/app/paper_market_session_guard.py` provides a **pure, non-executing** diagnostic review of caller-declared market session and bid/ask events. It does not fetch broker prices or venue calendars. No database, HTTP endpoint, broker key, order sender, trade, or migration is added.

It fails closed on CLOSED, HALTED, AUCTION, PREOPEN, POSTMARKET and UNKNOWN session states; mismatched provider/account/venue/instrument; stale or future status and quotes; transport delays; crossed/wide bid/ask; pre-session quotes; missing/partial replay checkpoints; duplicate/reordered/gapped session or quote sequences; reused event IDs; malformed prices; invalid timestamps; and unbounded freshness policies. Review digests bind the full declared input and policy but are **not** signed or trusted receipts. A passing diagnostic still returns `HOLD_RECONCILIATION` and `may_execute_paper_order = may_execute_real_order = false`.

## Prior-checkpoint integrity hardening

The diagnostic now checks the **previous** session and quote records for valid
observation/receipt ordering, bounded transport latency, consistent session-to-quote
chronology, uncrossed bid/ask, and the same spread ceiling as the current quote.
An adjacent sequence number is not enough to treat a malformed earlier checkpoint
as valid. Each failed check is visible in `failed_checks`; the decision still
remains `HOLD_RECONCILIATION` even when all declared checks pass.

These are *synthetic, caller-declared* checks, not evidence of provider
authentication, an accepted stop, or order eligibility. Previous checkpoints
must ultimately be sourced from a provider-authenticated, transactionally
persistent journal. No existing journal is changed by this patch.

**Provider-specific limitation:** Consecutive session/quote sequences are an *assumed* feed contract in these synthetic tests. Real providers may use different sequence semantics, may reset at session boundaries, or may not expose authenticated session events. Do not wire this into an execution path until a documented provider contract and source authentication are verified. An exchange's OPEN status alone does not establish instrument tradability, halt clearance, borrow eligibility, sufficient liquidity, available margin, protective stop acceptance, or executable quotes.

From `backend`: `PYTHONPATH=. pytest -q tests/test_paper_market_session_guard.py`. Test fixtures are synthetic.

## Integration handoff

Require an authenticated provider/venue market-status feed and executable two-sided quotes, then persist both source-specific sequence checkpoints in the **same** PostgreSQL transaction as paper risk reservation, order-intent quarantine and audit. Enforce source identity, trading calendar/DST, session transitions, instrument halts, broker acknowledgement, protective-stop coverage, margin and daily-loss circuit breaker before a future human-reviewed order. Unknown provider state, missing observations, crashes, gaps, mismatches and stale data must hold/quarantine rather than retry orders. Any real-money order requires fresh explicit owner confirmation for that exact order; this module can never provide it. Trading 212 public API documents Invest/Stocks ISA, not CFD accounts (official docs: https://docs.trading212.com/api/section/general-information/api-limitations, verified 26 October 2026).

Keep this PR draft/unmerged until exact-head CI and release/rollback verification; no production deployment or paid services.
