# Prior-hour-matched sweep control study (research only)

`frontend/lib/sweep-matched-baseline.ts` adds `compareSweepsToPastHourControls` on top of the causal v3 sweep follow-through helper in PR #17. It is not connected to the website, a broker, or an automated trading strategy.

## Predeclare the comparison

1. Choose one immutable source-isolated dataset, with exact provider/instrument/venue/price-side identity and verified source timezone convention. **Do not** concatenate independent monthly ZIPs or different UTC offsets merely to increase the sample. Provide completed candles and all `analyze(bars, 2, frame)` observations from that same window.
2. Fix the horizon, UTC timeframe, sample boundaries, round-trip cost assumption and seed **before** inspecting results. Example: `{datasetId:'verified-sha', instrument:'XAUUSD-OTC', frame:'1H', horizonBars:3, costBps:15}`, seed `'fixed-baseline-v1'`.
3. For each v3 completed sweep with a fully observed future horizon, select at most one distinct **non-sweep** control candle at the same UTC *close-hour* and with the same hypothetical direction. Control outcomes must have **fully matured before the sweep close**. Selection is deterministic from a fixed hash seed and does not inspect returns. Controls cannot be reused. Events without eligible prior controls are marked unmatched, never assigned zero returns.
4. Both sweep and control use next-bar open to fixed-horizon close, with the same assumed round-trip cost. Compare only matched pairs: report sweep net bps, control net bps, paired mean difference, matched/unmatched, pending, gap-excluded and price-excluded counts. The paired difference cancels a common fixed bps cost; **this does not cancel unknown broker spread/financing or make the strategy profitable**.
5. Repeat **only predeclared** horizons, market regimes and chronological evaluation windows; reserve a truly untouched forward period. Do not choose the most favorable seed or subgroup after looking at returns. Report negative results and missing controls.

This is a **descriptive historical baseline**, not a randomised experiment or an estimate of causal effects. UTC hour matching alone does not control day-of-week, news, session liquidity, regime, volatility, bid/ask spread, overlapping event labels, or time-varying broker fees. Prior controls can be from a different market regime. Outcomes overlap and are statistically dependent. Neither positive matched differences nor profitable-looking hypothetical returns prove a tradeable edge.

## Local verification

```sh
cd frontend
node --experimental-strip-types --test tests/sweep-matched-baseline.test.ts
npm test
npm run build
```

Ten synthetic regression tests check time-of-day/direction matching, prior-label maturity, deterministic prefix behavior, unique controls, event-order independence, equal-cost accounting, missing data, pending outcomes, overflowed numeric returns and fail-closed inputs. No licensed market data or broker credentials are committed. This helper requires PR #17's `sweep-outcome-study.ts` and `structure-quality.ts` and should not be cherry-picked onto main alone.
