# Week-clustered uncertainty for matched sweeps (exploratory research)

`frontend/lib/sweep-uncertainty.ts` adds `estimateSweepDifferenceUncertainty()` to the existing v3 sweep matched-control research in PR #17. It is a **standalone pure function**, not a UI, signal, trading strategy, order or deployed feature. It cannot verify a profitable edge.

## Protocol

1. Lock one immutable, source-isolated archive ID, instrument, frame, v3 detector version, UTC offset, horizon, transaction-cost assumption, baseline seed and bootstrap seed **before** looking at outcomes. Produce a `MatchedSweepComparison` with `compareSweepsToPastHourControls()` using only that archive. Do not mix monthly archives, venues, offsets, futures contracts or bid/ask price sides without a separately reviewed source-aware continuity protocol.
2. Call `estimateSweepDifferenceUncertainty(comparison, 'locked-week-bootstrap-v1')`. The helper validates paired chronology, control-label maturity, unique sweep timestamps, direction, and arithmetic. It groups observed sweeps into Monday-start UTC calendar weeks; every week is resampled as a whole (2,000 deterministic with-replacement bootstrap replicates). The reported percentile bounds are **descriptive 95% week-cluster bootstrap intervals for the mean paired difference in basis points**.
3. If fewer than 30 matched observations or fewer than 12 distinct event weeks exist, the helper returns `INSUFFICIENT_EVIDENCE` with **null bounds**, rather than misleading precision. This is a conservative reporting threshold, not a guarantee that 30 pairs/12 weeks provide adequate power.
4. Report every interval, mean, matched count, week count, seed, source identity, negative or inconclusive finding, and exclusion from the prior study. Do not select the most favorable market, seed, timeframe or horizon after examining results.

**Important:** Most of the currently imported archives are monthly. Each monthly archive has fewer than 12 calendar weeks, so **this helper intentionally refuses an interval for those archives**. An interval over a combined multi-month series would require verified identical provider/instrument/price-side/UTC conventions, immutable source hashes, cross-archive collision handling, and independently audited calendar continuity. Do not silently concatenate archives merely to make a significance-looking number appear.

## Limits

This is a nonparametric cluster bootstrap, not a valid causal inference or forward test. Resampling weeks preserves dependence **within** weeks but assumes independent weeks, which may fail under regime persistence or overlapping longer-horizon events. The percentile interval is not adjusted for multiple strategy searches, data snooping, different markets or repeated seed/horizon trials. It does not model actual spread, executable ask, CFD financing, slippage, market impact, broker fills or stop execution. A positive interval is not a real-money trading recommendation or a verified edge. Source UTC offsets remain unverified.

## Local tests

```sh
cd frontend
node --experimental-strip-types --test tests/sweep-uncertainty.test.ts
npm test
npm run build
```

Eight deterministic synthetic tests cover insufficient samples, constant positive/negative returns, repeatability, seed handling, event order, whole-week clustering, data mutation, invalid chronology, duplicate sweeps, forged arithmetic and numeric overflow. No private data, credentials or broker accounts are required.
