# Assumed-maintenance margin stress for open paper positions

`frontend/lib/paper-margin-scenarios.ts` exports `assessPaperMarginScenario()`, a **pure research-only** calculation for one **OPEN** quote-driven paper order. It does not close the position, contact a broker, infer a broker's margin policy, or decide whether an actual broker will liquidate.

## Inputs and calculation

Supply the exact paper source identity, an open order with its recorded entry price/time, an externally supplied **bid/ask** quote, and explicit scenario assumptions:

- `cashEquityBeforePositionCurrency`: account-equity baseline **before this position's price P&L, both sides' commissions and all supplied posted cashflows**. Do not include these charges again in the baseline. The caller is responsible for any unrelated open positions' unrealized P&L.
- `assumedMaintenanceRequirementCurrency`: a **positive, independently specified** maintenance requirement for the scenario, in the same account currency. This function does not derive broker contract notional, leverage, tiered rates or changing maintenance requirements.
- `otherReservedMarginCurrency`: separately assumed nonnegative margin reserved by other exposures. This is not their unrealized P&L.
- `maxQuoteAgeSeconds`, `asOf`, a scenario label and optional explicitly posted, source-identified financing/FX/borrow/adjustment cashflows. Missing funding charges are **unknown**, not zero. The cashflows' IDs are deduplicated and conflicts rejected.

For a BUY, the mark uses **bid**; for a SELL, it uses **ask**. The estimate is:

```
gross_unrealized = (mark - entry) * units * pointValue   [BUY]
                 = (entry - mark) * units * pointValue   [SELL]
estimated_equity = cash_equity_before_position + gross_unrealized
                 - (2 * commission_per_unit_per_side * units)
                 + known_posted_cashflows
assumed_maintenance = specified_maintenance + other_reserved_margin
headroom = estimated_equity - assumed_maintenance
```

The result flags `AT_OR_BELOW_ASSUMED_MAINTENANCE` at zero or negative headroom. This is **not** a broker margin call, forced liquidation, available cash, executable fill, or liquidation-price forecast. Real brokers can liquidate earlier, later, partially, at worse prices, or use different closeout thresholds. Scenario quotes may be hypothetical; no price is invented by the function. The calculation omits partial fills, variable spread/impact, FX conversion of contract notional, actual margin tiers, portfolio offsets, broker rules and unsettled charges. All results remain `DECLARED_UNVERIFIED_SCENARIO`.

Quote identity, noncrossed positive prices, entry-time ordering, receipt time, as-of cutoff and freshness are checked; invalid or non-finite arithmetic fails closed. The caller must verify quote authenticity and account-currency units externally. The function never mutates input state or the paper ledger.

## Synthetic verification

From `frontend/`:

```sh
node --experimental-strip-types --test tests/paper-margin-scenarios.test.ts
```

Eight deterministic tests cover BUY/SELL marks, a gapped SHORT loss that crosses an assumed threshold, explicit financing, changing maintenance assumptions, source/timestamp rejection, duplicate cashflow IDs, overflow and input immutability. These tests do not establish a broker's actual margin rules or any trading edge.

## Next integration gate

Before exposing this in a broker-facing UI, collect **authorized** broker-specific account currency, contract multiplier, quote-side, maintenance margin requirements, time-stamped collateral and posted financing data. Build an append-only, restart-safe demo journal and reconcile its state against independently obtained broker demo statements. Do not automatically liquidate or route real orders based on this research-only flag.
