# Confluence stop/target risk-path study (research only)

This independent pure TypeScript helper, `frontend/lib/sweep-confluence-risk-path.ts`, consumes completed signals from `studySweepConfluence` and the **same source-isolated 1H candles**. It is not wired to production APIs, alerts, paper order submission, or any real broker. It does not certify CRT/ICT confluence or a profitable edge.

## Frozen `sweep-confluence-ohlc-risk-path-v1` rules

- Accept only `sweep-mss-fvg-same-close-v1` 1H completed signals with matching next-open prices and causal sweep/confirmation ordering. No re-selection using future outcomes.
- Entry is at the first candle open after completed confluence confirmation. Require a contiguous, complete source segment and at least `atrPeriod + 1` valid historical candles through confirmation close.
- At the entry open, use a simple average true range computed **only through the confirmation close**; set directional stop `entry ± ATR × stopAtrMultiple` and target `entry ± stopDistance × rewardRisk`. These are hypothetical levels, not an executable order.
- Evaluate up to `maxHoldBars`, never longer than the original study's fixed outcome horizon. On the entry bar and subsequent bars, stop and target are checked using OHLC. If both are touched, **stop wins**. Adverse opening gaps fill at the worse open; favorable opening gaps fill at target with no favorable price improvement. Otherwise exit at the final completed bar's close.
- Strict chronological, nonoverlapping positions only; subsequent signals arriving while a simulated position is open are excluded. A partial/gapped bar while a position is open makes the outcome unknown and blocks subsequent signals in that source segment rather than inventing a flat fill.
- Compute directional price returns and illustrative `netBps = grossBps − assumedRoundTripCostBps`; divide by ex-ante price risk in bps for net R. Cost scenarios must be explicit, finite, sorted and unique. Null means no completed eligible trades, not zero profit.

The study's original `signals` include only **completed fixed-horizon observations**. Pending/unconfirmed events are not included here; this is conditional retrospective research, not an all-signal prospective fill journal. Reusing previously inspected archives does **not** create an untouched holdout. The engine's ATR, stop and target values are not optimized on these observations; preserve the chosen settings and version when testing new data.

## Reproduce

From `frontend`:

```sh
node --experimental-strip-types --test tests/sweep-confluence-risk-path.test.ts
npm run typecheck
npm test
```

Ten synthetic tests exercise stop-first OHLC ambiguity, next-open execution, adverse opening gaps, conservative favorable fills, timed exit, bearish symmetry, causal invariance, incomplete candles, parameter gates and input tampering. Synthetic tests do not measure profitability.

## Explicit exclusions and release

BID-only historical OHLC cannot prove tradable ask/bid spread, broker fill, margin, financing, rollover, liquidity, news/calendar availability, commissions, FX settlement, contract point value or stop-order behavior. Hypothetical round-trip costs do not replace those inputs. No live, demo or paper order is sent by this helper. Do not use positive returns as live signals. Keep PR draft/unmerged until latest-head backend/frontend/Docker/cloud CI passes and the exact Render workspace, backup, rollback and health checks are verified; `main` may auto-deploy.

**Handoff:** Obtain newly timestamp-authenticated, authorized bid/ask candles and broker-specific financing/cost rules, pre-register parameters, evaluate untouched chronological periods and clustered uncertainty, then validate independently in a prospective disconnected paper journal. Never connect an unsupported Trading 212 CFD order endpoint or enable autonomous real-money trading.
