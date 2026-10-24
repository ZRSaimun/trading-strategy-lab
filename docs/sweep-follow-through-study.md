# Causal sweep follow-through study (research only)

The standalone `frontend/lib/sweep-outcome-study.ts` helper measures **fixed-horizon descriptive returns** following `structure-research-v3` completed-candle sweep observations. It is **not** connected to the website, a live quote source, a broker, or the existing strategy simulator.

## Reproducible evaluation protocol

1. Load one exact source-isolated dataset. Verify its instrument, provider, price side, timezone convention, dataset hash and trading-session coverage. Do not concatenate different archives or brokers.
2. Aggregate into a chosen timeframe, retaining actual `observed_minutes` and incomplete buckets. Produce events using `analyze(bars, 2, frame)`; do not use hindsight to decide which events to include.
3. Pass those events and the **same bars** to `studySweepOutcomes(bars, observations, {datasetId, instrument, frame, horizonBars, costBps})`.
4. Predeclare the horizon and assumed round-trip cost. Evaluate bullish sell-side sweeps and bearish buy-side sweeps in the direction of the observation, **not** as automatically executable trade signals.
5. Entry reference is the **next candle open**, and outcome is the close of the `horizonBars`-th candle after the observation. A horizon of 1 uses the next candle's close. Subtract the configured cost in basis points. Incomplete future horizons remain pending, and any gap or partial candle between event and horizon is excluded. Nonpositive entry/exit prices are excluded because percentage returns are undefined.
6. Report every included, pending and excluded event. The mean and positive fraction are descriptive; overlapping outcomes are dependent. Compare with predeclared unconditional and random-time baselines and genuine later, untouched periods before drawing conclusions.

The helper fails closed on duplicate/backward timestamps, ambiguous repeated sweep observations, incompatible rule versions and invalid cost/horizon settings. It does not modify imported candles, saved strategies or historical records.

**Limitations:** Source authentication and timezone conventions are upstream responsibilities. Historical BID-only prices cannot establish executable entry/exit fills or round-trip spreads. There are no stops, targets, order sizes, margin, overnight CFD financing, news rules, session calendars, live quotes, broker fills or real-money orders. A positive historical average—even after an assumed cost—is not proof of a trading advantage. Research multiple-testing and selection effects must be disclosed.

## Local verification

```sh
cd frontend
npm ci
npm test
npm run build
```

The seven deterministic tests cover entry/exit timestamps, signed direction, cost sensitivity, prefix maturity, gaps, incomplete candles, price validity, version checks and ambiguous timestamps. All examples use synthetic prices only. Production deployment is unnecessary for this standalone research helper.
