# Disconnected paper protective-stop monitor (experimental)

`backend/app/paper_stop_monitor.py` is an isolated, pure function for **observing** a protective-stop breach on a supplied synthetic or owner-declared bid/ask quote. It has no API route, provider integration, journal mutation, broker connection or order submission. The output always reports `may_execute_paper_order=false` and `may_execute_real_order=false`. A breached stop is **not** a fill, an accepted broker stop, or permission to trade.

## Conservative behavior

- Requires exact instrument/provider/venue match, positive and uncrossed bid/ask, bounded spread, server-clock freshness and transport lag.
- Rejects duplicate quote IDs, non-increasing provider sequence numbers and non-increasing observation timestamps **relative to the supplied prior snapshot**. The caller must maintain an authenticated, persistent prior state; this pure function does not do so. A previous checkpoint is now **all-or-none**: prior sequence, observed timestamp and quote ID must all be present, or all absent for a first observation. Dropping just one replay field fails closed.
- Caps the caller-specified quote-age policy at **60,000 ms** (minimum 100 ms), preventing an accidental or malicious multi-minute/hour freshness override. This is an upper bound on policy configuration, not evidence that a quote is genuine, executable or safe for an order. The default remains 3,000 ms.
- For an existing hypothetical **LONG**, a stop is observed only when the **bid** is at or below the stop; for **SHORT**, only when the **ask** is at or above it. A gap beyond the stop is flagged and priced at the observed adverse quote, not optimistically at the stop. The candidate price is still **not an executable fill**.
- Uses bounded decimal strings and exact `Decimal` calculations for cash P&L. `point_value_cash` must already include a verified instrument multiplier and account-currency conversion. Estimated exit costs are owner assumptions, and unknown costs may be higher.
- Stale, replayed, crossed, over-spread, future-dated or mismatched quotes fail closed and produce no candidate price or P&L. They require manual reconciliation rather than assuming the stop was or was not filled.
- Never bypasses a broker's stop mechanics, margin policy, trading halt or account-wide circuit breaker. No stop is automatically placed, canceled or modified.

## Limitations and integration handoff

The input is **untrusted**; `quote_authenticated` and `position_authenticated` are always false. A matching source string, quote ID, or hash does not establish authenticity. Bid/ask snapshots cannot prove historical intra-quote touch ordering, partial fills, queue priority, slippage, venue execution or guaranteed stop protection. There is no take-profit engine. `requires_human_reconciliation` is advisory; a production workflow must fail closed if an expected stop state is unknown. Never use this function to generate an order directly.

Before any paper-journal integration, add a verified demo quote adapter with server-side receive timestamps, persistent per-source sequence checkpoints, authenticated account positions, journal/risk reservation atomicity, duplicate-stop-event prevention across workers, rate limits and audited reconciliation. Exercise disposable PostgreSQL concurrent writers and process restart, plus stale-feed and gap scenarios. **No CFD API support is implied.** Trading 212's public API documentation describes Invest and Stocks ISA, not CFD order execution: https://docs.trading212.com/api.

Run from `backend`: `PYTHONPATH=. python -m pytest -q tests/test_paper_stop_monitor.py`. The synthetic suite does not demonstrate broker connectivity or profitability.
