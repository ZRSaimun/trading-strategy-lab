# UTC-week leave-one-out influence (research only)

`auditConfluenceWeekInfluence(report)` is an isolated, deterministic diagnostic for a **frozen** confluence OHLC risk-path report. It first runs the existing source/cost/chronology auditor, then removes one UTC Monday–Sunday event-week at a time without modifying, refitting or reselecting any trade. Per predeclared round-trip cost it reports the full-sample mean net R/bps, lowest/highest leave-one-week-out mean R, maximum absolute mean-R shift, corresponding UTC Monday timestamp and count of robust nonzero mean-sign reversals. Ties select the earliest UTC week. It also discloses the largest event-week share of trades.

For fewer than **30 completed paths or 12 distinct event weeks**, influence estimates and sign-flip counts are `null` and status is `INSUFFICIENT_EVIDENCE`. This arbitrary reporting floor is not a power calculation. A positive full-sample mean with a negative leave-one-week-out mean is a fragility warning, **not** a trading signal; an absence of flips does not establish an edge.

This is **not** independent out-of-sample validation, a multiple-testing correction, a confidence interval, a broker-executable backtest, cash drawdown, a live quote or a real order. Historical BID/OHLC prices, source timestamps, spread, financing, slippage and contract terms require separate verification. No source archives, credentials or order state are accessed or modified.

Synthetic regressions: `cd frontend && npm test`; targeted: `node --experimental-strip-types --test tests/sweep-risk-path-week-influence.test.ts`.
