# Causal hourly volatility regime (research-only)

`frontend/lib/causal-volatility-regime.ts` adds a **frozen, deterministic volatility hypothesis label**. It does not optimize an entry rule or trade.

## Predeclared protocol

- Input: one exact archive/dataset ID and instrument; strictly increasing UTC-aligned completed **1H** candles with 60 observed minutes and valid, positive OHLC.
- True range for a completed bar is max(high-low, |high-prior close|, |low-prior close|).
- ATR(14) uses the current completed bar and 13 preceding completed bars, with the prior close of the fourteenth bar. Normalized ATR is `ATR / current close × 10,000` bps.
- Compare the current normalized ATR only to the **24 prior completed** normalized ATR values in the same contiguous segment. Percentile = `(number lower + 0.5 × number tied) / 24`; ties use a fixed relative numerical tolerance.
- `LOW` if percentile < 1/3, `HIGH` if > 2/3, otherwise `NORMAL`. No outcome-optimized thresholds.
- First possible label in each contiguous valid segment is index 38 (zero-based). Labels are observed only at the **candle close** and may first be used at the following candle open. No signal at the open of the candle being classified.
- Any missing, malformed, incomplete, nonpositive-price or noncontiguous candle resets warmup. No market-hours inference or synthetic candle filling.
- Output is a descriptive sequence of labels, counts and skipped candles. A label is not a buy/sell signal or a volatility forecast.

## Validation and limits

Run `cd frontend && npm test -- --test-name-pattern=volatility` only if your Node test-runner setup supports filtering; the standard project command `npm test` includes `tests/causal-volatility-regime.test.ts`. Typecheck with `npm run typecheck`.

Tests cover constant ranges, widened/narrowed ranges, completed-candle availability, future-prefix invariance, invalid timestamps, gaps, partial candles, invalid prices, source identity and zero input.

This module does **not** bind candles cryptographically to an archive, prove exchange session completeness, model executable bid/ask, trading costs, financing, slippage or realized P&L. The normalized ATR terciles are hypotheses for a **future pre-registered** interaction study against untouched, source-verified data. Do not select the most profitable tercile on already inspected archives and call it an independent edge. No UI, broker, database, migration, paid provider or production path is touched.

**Release:** draft PR #24; do not merge/deploy until full latest-head CI and production workspace/backup/rollback/health gates are verified.
