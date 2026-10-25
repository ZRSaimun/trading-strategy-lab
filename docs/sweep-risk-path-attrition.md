# Confluence risk-path attrition audit (offline, research only)

`auditConfluenceRiskPathAttrition(reports)` is a pure, deterministic summary of **why frozen confluence signals do or do not become eligible completed OHLC risk paths**. It consumes source-isolated `RiskPathReport` objects and does not read candles, modify archives, connect to a provider, submit paper/live orders, or create an API route.

The helper first invokes the existing independent source-influence auditor, which validates report accounting, trade chronology, stop/target and cost arithmetic, exact instrument/configuration consistency, unique archive identifiers, and non-overlapping selected trade intervals. It then reports pooled and per-archive `inputSignals`, `closed`, `pending`, `gapExcluded`, `warmupExcluded`, `overlapExcluded`, and `priceExcluded` counts. Each count is retained in its original category; **excluded or pending paths are never assigned a zero return, a stop-loss, or a profit**.

- `eligibleShare = closed / inputSignals`; `excludedShare = 1 - eligibleShare`. Both are `null` when no input signals exist.
- `unresolvedShare = (pending + gapExcluded) / inputSignals`. This is an operational subset of exclusions, **not** the full set of missing-not-at-random paths; ATR warmup, overlapping signals and invalid prices also affect selection.
- `equalSourceEligibleShare` averages per-source shares **only across archives with a nonzero signal denominator**. It is not the pooled share and does not make archives statistically independent.
- `sourceEligibleShareRange` is descriptive only, not a confidence interval or a holdout test.

Inputs are bounded by the existing 1–100 source-report limit and 100,000 closed paths per source; pooled counts are checked for safe-integer overflow. Results are stable under source input permutation. Archive identifiers and non-overlapping selected trades **do not** prove that the underlying candle windows are independent or that vendor data is authentic. A separate source-coverage/provenance audit is needed before interpreting multi-archive aggregation as independent evidence.

## Reproducible synthetic tests

From `frontend/` on Node 22:

```sh
node --experimental-strip-types --test tests/sweep-risk-path-attrition.test.ts
```

All fixtures are synthetic. Do not infer historical profitability from these tests. Historical retrospective confluence evidence remains 41 Nasdaq hypothetical eligible paths with negative mean net R at illustrative 5 bps; real broker spreads, financing, quotes and genuinely untouched holdout outcomes are not established. Keep this module disconnected from execution, production data and deployment until normal release gates pass.
