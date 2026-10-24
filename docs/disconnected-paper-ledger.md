# Loop 5 — disconnected two-sided paper journal (research only)

This additive, pure TypeScript component is **not an operational demo trading account**, broker connection, order router, persistent ledger, or authenticated price feed. It does not read the historical BID-only archive or make executable-quote claims. The caller supplies an explicitly named source and all events. Output is always `UNVERIFIED_LOCAL_RESEARCH`, `live=false`, `quoteAuthenticated=false`, `ordersSubmitted=0`, `persisted=false`.

## Contract

`replayDisconnectedPaperLedger(events, source, policy)` accepts a contiguous append-only *in-memory* sequence of quote, simulated open and simulated close events. Quotes must be explicitly two-sided `bid < ask`, positive, strictly time-increasing, and match the full instrument/provider/venue/source/currency identity. An open or close references the latest quote sequence, respects the quote-age limit, and cannot move backwards in time. Exactly one position may be open. Trade IDs cannot be reused, and a close requires a quote newer than its open. This is deterministic replay, not proof that quotes were seen in real time: **caller timestamps are not trusted server receipts**.

Long opens at ask and closes/marks at bid; shorts open at bid and close/mark at ask. Each simulated fill adds adverse caller-declared slippage; open-position marks add optional adverse stress slippage. Cash/notional caps reject leverage; no margin, borrowing, financing, market-hours, corporate actions, liquidity, minimum lot size, tax, settlement, or broker-specific order rules are modeled. Entry and exit fees reduce realized net P&L. The report includes closed trade outcomes, open unrealized P&L, equity path, peak, absolute and fractional peak-to-trough drawdown, and closed-trade win rate (null without closed trades).

**Financial precision warning:** calculations use JavaScript numbers, not accounting-grade fixed-point currency. Do not use this module for settlement, reconciliation, or actual account balances. A synthetic positive P&L is not evidence of a profitable trading edge. Without a trusted forward quote feed, executable bid/ask, realistic spreads, costs and fills, even demo outcomes remain unverified.

## Verification and boundaries

Run `cd frontend && npm test` and `npm run typecheck`. Synthetic tests cover bid/ask side, both fees, slippage, drawdown, losing trades, open positions, duplicates, quote staleness, sequence/time regressions, cash/notional limits, source mismatch and deterministic replay.

This module intentionally does **not** import Loop 3 demo-fill reconciliation, Loop 4 order preview/risk reservations, or Loop 1 archive/receipt code. It cannot turn on alerts or submit broker orders.

## Loop 1 handoff

Provide (1) authorized source-authenticated *prospective* bid/ask quote observations with server-owned receipt timestamps and session/calendar semantics; (2) durable transactional append-only quote/order/outbox records and restart-safe idempotency; (3) two-worker concurrency and crash/replay tests; (4) verified independent notification receipts; (5) separate approved broker-account and quote eligibility checks before any future manual live-order preview. Historical BID candles and self-declared timestamps cannot satisfy these requirements. Never auto-submit real-money orders.
