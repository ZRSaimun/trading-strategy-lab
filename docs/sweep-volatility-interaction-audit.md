# Frozen volatility × confluence interaction audit (offline only)

`frontend/lib/sweep-volatility-interaction-audit.ts` joins two existing **research-only** outputs: the `sweep-confluence-ohlc-risk-path-v1` report and the `causal-1h-natr-terciles-v1` label report. It is **not** a live strategy, order router, or claim of profitability.

## Protocol (fixed before untouched evaluation)

1. Require identical exact `datasetId` and `instrument`, fixed ATR(14)/24-prior-rank 1H regime metadata, and independent validation of risk-path stop/target, chronology, accounting and hypothetical costs.
2. Match only a label whose completed candle closes **exactly at the risk path's next-open entry timestamp**. Require `observedAt = candleOpenAt + 3600 = eligibleFrom = trade.entryAt`. Later labels never classify earlier entries. No interpolation, gap filling, or use of outcome candles to label entries.
3. Validate label ordering, UTC alignment, finite positive NATR, percentile, LOW/NORMAL/HIGH thresholds, and all regime/accounting totals. Exact IDs and these checks are **not** cryptographic archive authenticity.
4. Report **all** LOW, NORMAL, HIGH, and UNLABELLED paths, including the latter in the denominator; do not silently discard missing labels or assign zero returns. Report mean net bps and mean net R for every previously frozen flat-cost scenario. Do not rank regimes, select thresholds, or change signals.
5. Mark an individual regime `DESCRIPTIVE_ONLY` only with at least 30 completed paths and 12 UTC event weeks. Overall `DESCRIPTIVE_ONLY` additionally requires all three regimes to meet that threshold and no unlabelled paths. Even then no significance or profitable edge is implied.

Run `cd frontend && npm test` and `npm run typecheck` with the project dependencies. The 10 synthetic tests cover exact temporal joins, future-label nonuse, missing labels, invalid source IDs, forged timestamps/ranks/counts, tampered return arithmetic, empty inputs and descriptive minimums.

**Limits:** Retrospective already-inspected archives cannot be promoted to independent holdouts. Source identities may alias the same underlying data. BID/OHLC simulated stops and assumed costs are not executable quotes or broker fills; real spreads, slippage, financing, leverage and account equity are not represented. Prospective testing requires externally verified source timestamps, frozen eligibility rules, purged chronological holdouts, prespecified multiple-comparison handling and actual executable quote/fee evidence. This module has no UI, API, broker, database, migration, paid-provider or production effect. Keep PR #24 draft until full CI and production safety checks pass.
