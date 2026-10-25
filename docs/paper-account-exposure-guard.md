# Paper account-wide exposure guard — offline stress review

This is a **read-only, disconnected** Python research component. It adds a conservative account-wide view of declared open positions, pending orders and ambiguous cancellation/outcome states. It does not authenticate a brokerage account, submit demo/live orders, persist reservations, release a cancelled order, or confirm protective stops. Even a result of ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED **never grants execution permission**. Both paper and live order execution flags always remain false.

## Contract

Import evaluate_paper_account_exposure from app.paper_account_exposure_guard and call it with a strict account snapshot and a trusted server epoch-millisecond clock. The complete schema and synthetic fixture are in backend/tests/test_paper_account_exposure_guard.py. Every decimal amount, price, quantity, rate and policy threshold must be a finite bounded string. Binary floats, scientific notation, unexpected fields and accidental credential fields are rejected. The caller must provide a full inventory for one account and one currency; this module cannot establish completeness or source authenticity. Do not pass raw API keys, tokens or customer identifiers.

Each exposure has OPEN, PENDING, CANCEL_REQUESTED or OUTCOME_UNKNOWN state. All states consume full declared quantity, so a requested cancellation cannot release risk. Unknown/cancel-requested outcomes force HOLD_RECONCILIATION until separate authenticated broker-side reconciliation resolves them. Duplicate client order IDs, too many open/pending orders, excessive same-symbol order count, per-symbol notional concentration, per-position stressed loss, aggregate daily downside, gross leverage and reserved margin are evaluated independently.

For each exposure, strict bid/ask ordering, spread, quote observation/receipt times and transport lag are checked against a caller-supplied trusted clock. A pending order cannot assume a better entry than the current ask for LONG or bid for SHORT. Protective stops must be on the loss side of entry and stressed exits must be worse than the stop. Long positions use bid and shorts use ask for the potential give-back of existing unrealized gains. **If the executable quote is already worse than the supplied stressed exit, the worse executable quote is used in loss calculations**; a long bid at/below its stop or short ask at/above its stop triggers `no_breached_protective_stops=false` and `HOLD_RECONCILIATION`, even if the requested stop placement is valid. A stop touch is not proof of a fill, and the caller must obtain independent broker-side reconciliation. The account-wide daily downside includes realized losses, only adverse aggregate unrealized P&L, and the full stressed exposure loss. This can double-count some loss by design, so it is a conservative scenario, not an accounting statement. The evaluator also subtracts that downside from declared equity to calculate `stressed_equity_cash`, then rechecks gross leverage and reserved margin against **stressed** equity. A portfolio may pass both current-equity caps but still return `HOLD_RECONCILIATION` on `stressed_gross_leverage_within_cap` or `stressed_reserved_margin_within_cap`. Nonpositive stressed equity fails both checks. This deliberately conservative headroom is not a broker margin-call forecast or evidence of available collateral.

The module returns deterministic checks, exact Decimal-string aggregates, SHA-256 order aliases (not broker signatures), explicit failed-check names, and permanent false flags for account/quote authentication, verified complete inventory, broker-side stops, durable reservations, owner approval and execution.

## Limitations and release gates

- The account snapshot, quotes, contract point values, FX conversions, margin rates, session state and even the supplied clock are unverified caller assertions. A consistent calculation does not prove the broker's actual exposure. A timestamp alone does not authenticate a quote or prevent quote replay.
- This is not a VaR model, correlated-market scenario engine, liquidation estimate or guarantee of maximum loss. Gaps, spread expansion, liquidity, financing, currency conversion, margin calls and unknown orders can produce larger losses. A stop request is not a fill.
- The per-symbol notional cap uses symbols exactly as supplied, not verified underlying exposures or correlated proxies. Gold futures, Gold CFDs and ETFs are not automatically grouped. A separate canonical-instrument mapping and concentration/correlation policy are needed.
- The result is not connected to paper risk reservations (PR #26), daily-loss breaker, quote+journal atomic store, broker snapshot reconciliation, durable order-intent quarantine or owner-reviewed order preview. Integration must use one database transaction or explicit durable reconciliation barriers; checking independent outputs sequentially would introduce time-of-check/time-of-use risk.
- No FastAPI route, broker adapter, key storage, audit database write, schema migration, paid call or production deployment is added. This pure function should be run only on synthetic or authorized inputs. No real-money execution without separate secure provider credentials and explicit positive approval for each specific order.

Trading 212's official Public API at https://docs.trading212.com/api was checked on 25 October 2026: it is beta, and available only for Invest and Stocks ISA, including its demo environment. Its documented API does not support Trading 212 CFD order execution.

## Test

Run from backend:

    PYTHONPATH=. python -m pytest -q tests/test_paper_account_exposure_guard.py
    python -m compileall -q app/paper_account_exposure_guard.py

The synthetic tests cover fresh/stale quotes, crossed/wide spreads, short-side pricing, stressed stops, pending/cancel/unknown order counting, duplicate IDs, daily downside, current and stressed-equity leverage, current and stressed-equity margin, concentration, emergency latch, session closure, malformed data and immutable execution-denial flags. Passing local tests alone does not establish compatibility with the latest main; run exact-head CI before considering a merge. Do not deploy until the correct Render workspace, backup/rollback and health checks are independently verified.
