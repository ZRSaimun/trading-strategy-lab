# Quote, duplicate-order and circuit-breaker preview (research only)

The owner-authenticated `POST /api/broker/order-gate-preview` is a **stateless diagnostic**. It accepts a nested `risk` object using the existing stress-preview schema and a `controls` object containing owner-declared bid/ask quote, exact provider/venue/instrument identity, observed/received timestamps in **UTC epoch milliseconds**, client-order ID, a list of prior IDs, open/pending-order flag, kill switch, market session, realized daily P&L, loss-streak cap and explicit owner-confirmation flag.

The backend uses **its own current clock** to check quote age and transport delay. It rejects crossed/zero/overflowed spreads, mismatched instruments, unreasonably wide spreads, stale/future/late quotes, previously seen client IDs, outstanding orders, kill switch activation, market closures, daily loss/streak caps and missing owner confirmation. The daily loss check also subtracts the proposed stressed loss from today's realised P&L, so an order that would breach the selected cap is rejected even before that cap is reached. It also requires the hypothetical entry not to be more favorable than the supplied bid/ask and all existing stressed loss/margin/leverage assumptions to pass. Trading 212 CFD is marked unsupported by its documented public trading API.

## Critical limitations

**This is not a real order gate or a broker connection.** All quotes, balances, P&L, provider names, existing-order flags, client IDs, market-open status and confirmations are **user declarations**, not authenticated provider/account data. The function does not persist anything, atomically reserve IDs, enforce a kill switch across workers or restarts, or submit a demo/live order. An apparently passing preview is not execution permission. Responses always include `may_execute_real_order=false`, `may_execute_paper_order=false`, `quote_authenticated=false` and `durable_circuit_breaker=false`. No account key or secret is accepted.

The preview only supports positive bid/ask prices. It does not model negative-price contracts, partial fills, account currency conversion, exchange halts, CFD financing, margin calls, order-book depth or broker liquidation. A protective stop does not guarantee a loss limit. There is no profitable trading strategy claim.

## Tests and next integration

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_order_gate.py tests/test_order_gate_api.py tests/test_broker_stress.py
```

Before using this logic in paper execution, integrate a source-authenticated quote adapter and **transactional durable order-ID reservations** with restart-safe account-wide kill-switch and P&L state. Verify provider-specific bid/ask and exact instrument contract details; then compare against authorized demo broker fills. Do not enable real-money execution without eligible official broker API, scoped credentials, hard limits, and explicit confirmation of each proposed order.

This feature is additive to PR #14. PR #18 owns the separate in-memory paper ledger; avoid editing its files or assuming this preview provides the persistence missing from that ledger. Do not merge to production until the Render workspace, backups, rollback and all latest-head CI jobs are verified.


## Account-wide downside reservation (24 October 2026)

The stateless preview now accepts two additional **owner-declared** fields in `controls` (both default to zero for backwards compatibility):

- `daily_unrealized_pnl_cash`: signed mark-to-market P&L of other open positions, in the same account currency. Only the negative portion counts; floating gains cannot be used to justify more risk.
- `other_positions_reserved_stress_loss_cash`: nonnegative incremental potential downside of other open or pending exposures **beyond** their already marked unrealized P&L. Do not double-count current floating losses.

The effective account-wide daily P&L assumption is `daily_realized_pnl_cash + min(daily_unrealized_pnl_cash, 0) - other_positions_reserved_stress_loss_cash`. The preview checks this against the daily loss cap, then deducts the proposed order's stressed loss and checks again. Both checks fail closed for nonfinite aggregate results. The response reports the components in `account_wide_daily_loss_scenario`. Synthetic tests cover existing exposure, positive floating P&L, negative reservations, and arithmetic overflow.

**Important:** defaults of zero mean **unknown exposure, not verified absence of exposure**. Neither account positions nor mark-to-market P&L nor reserve totals are fetched from a broker. Do not treat a passing preview as proof that portfolio limits are satisfied or as permission to place a paper/live order. Before real execution, require broker-authenticated account-wide positions, signed current quotes, currency conversion, transactionally reserved risk and persistent cross-worker kill switches. The calculation is intentionally conservative about unrealized gains, but cannot bound actual gap loss or liquidation risk.


## Account-wide margin and gross leverage (24 October 2026)

A proposed trade can pass **its own** margin and leverage checks while other open or pending positions already consume the account's capacity. The owner-declared `controls` object now also accepts:

- `other_positions_reserved_margin_cash`: nonnegative total **existing** reserved margin, in the same account currency as the hypothetical equity.
- `other_positions_gross_notional_cash`: nonnegative total absolute gross notional of **other** open/pending exposures, converted to the account currency. Long and short positions must not cancel one another.

Both default to zero solely for backwards compatibility; **zero is not evidence that the account is empty**. The response includes a `portfolio_exposure_scenario` with existing and proposed margin/notional, combined leverage and `inputs_broker_verified=false`. The preview independently fails `portfolio_margin_within_equity` if existing reserved margin plus proposed margin exceeds hypothetical equity, and fails `portfolio_gross_leverage_within_cap` if (existing gross notional + proposed gross notional) / equity exceeds the selected leverage cap. The additional `portfolio_margin_arithmetic_valid` and `portfolio_gross_arithmetic_valid` checks fail closed if floating-point overflow or precision loss hides a positive proposed increment.

These are **illustrative account-wide gates, not a broker-verified free-margin, buying-power or liquidation model**. Equity may not equal available collateral; margin may be tiered, hedged, currency-converted or increased by the broker without notice. There is no account or provider connection, and passing checks never enables paper or real orders. Before activation require authenticated current broker equity, all positions/pending orders, gross exposure, margin reservation, bid/ask and currency conversion, plus transactional risk reservation and kill switch.

Synthetic regressions:

```sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_portfolio_risk_gate.py tests/test_order_gate.py tests/test_order_gate_api.py
```
