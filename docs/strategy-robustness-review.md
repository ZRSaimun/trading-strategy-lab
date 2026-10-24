# Strategy Robustness Review (research only)

Open **Strategy Robustness** from the terminal navigation to inspect previously saved **Backtesting** simulation reports, in either authenticated private-server mode or GitHub Pages browser-local mode. The view reads existing `/research/backtests` records; it does not import market prices, fit strategies, modify data, place orders, or require external subscriptions.

## What the review does
- Compares each *versioned strategy* separately across the saved full-sample, 60% development, 20% validation, and 20% holdout metric records.
- Shows returns, trade counts and maximum **close-marked** drawdown in the existing report's own modelled cost units.
- Highlights holdout samples with fewer than 30 simulated trades, negative holdout return, a reversal from positive development to negative holdout, a 15-percentage-point drop in historical win rate, or at least 20% simulated drawdown. Thresholds are descriptive heuristics, **not** statistical hypothesis tests or investment signals.
- Highlights missing segments, undefined profit factors, no trades, unknown source provenance, and input-window-cap warnings.
- Refuses malformed numeric metrics, duplicate strategy identities or duplicate split labels.

## Scientific and trading limitations
- Existing splits are chronological but **not locked holdouts**. Repeatedly looking at results, choosing settings or comparing many variants can overfit them.
- Each split in the current simulator has independent warmup, starting capital and liquidation; segment returns are not additive and cannot establish live generalisation.
- Historical price candles and simulated OHLC fills are **not** broker execution, actual tick liquidity, executable bid/ask spreads, financing or confirmed profit.
- A warning not triggering is **not** an endorsement or evidence of positive expected return.
- A true walk-forward or purged rolling evaluation with pre-registered tuning, untouched final test set, realistic contracts/costs and later paper trading remains separate work.

## Time-based expanding-window forward evaluation

The **Strategy Robustness** screen now offers an **on-demand**, read-only, time-based forward evaluation on a saved backtest's exact candle snapshot. It does not call external data providers, submit orders, change research records or fit a model on forward-test candles.

- Requires a saved snapshot of **500–20,000 complete aggregate candles**, matching coverage metadata and the current version of the deterministic simulator. The saved full-sample strategy report must also match the snapshot's start/end/bar count, and its trade count, net return, win rate, profit factor and close-marked drawdown must be reproducible with the saved engine settings. Missing, duplicate, unordered, altered or incomplete aggregate data fails closed when these checks detect a mismatch.
- Divides the observed elapsed UTC period into five equal-duration intervals, **not** five equal-count candle buckets. Unknown market closures and source gaps remain gaps. A fold fails if its calendar-time interval has fewer than 200 training or 100 test candles.
- Uses expanding past-only training windows: first 40%, 60%, then 80% of elapsed history; the following non-overlapping 20%-duration periods are independent forward tests. Boundaries are based on time, not outcomes.
- For one chosen versioned strategy, training tests at most three **predeclared lookbacks**: the saved lookback, its half (minimum 3), and its double (maximum 500). If any candidate has **30 or more training trades**, the highest training average R is selected (ties prefer the saved lookback). If none qualifies, the original saved lookback is retained **without optimization**. No test-period metrics influence selection.
- Each forward test starts its own warmup and starting capital. No position, candidate or equity crosses a boundary; folds are not compounded or added into a synthetic portfolio return.
- Shows fold-level selected lookback, training/test trade counts, test return, test average R and close-marked drawdown, with descriptive caution flags for thin samples, negative return, and high drawdown.

**Limits:** Replaying a baseline checks *internal consistency only*. It does not cryptographically authenticate the market-data source or verify the raw archive's dataset hash, broker fills or entitlement. This is a small historical walk-forward sensitivity experiment, **not** a protected untouched holdout, robust parameter search, or profitability proof. All test periods become visible once inspected; repeated research or expanding the candidate grid after inspection introduces multiple-testing bias. Real bid/ask execution, slippage, exchange calendars, contract metadata and independently observed paper-trading results remain unverified. A longer licensed archive and a preregistered final untouched evaluation are needed before treating results as evidence of an edge.

Regression coverage: `frontend/tests/walk-forward.test.ts` checks chronological fold isolation, future-price invariance of earlier folds and training choices, low-trade no-fit fallback, source/coverage version failures, invalid lookbacks, tampered saved metrics, changed snapshot reproducibility and thin calendar-time coverage.

## Verification
`frontend/tests/research-review.test.ts` covers return reversal, small holdouts, drawdowns, no-trade cases, missing segments, source uncertainty, strategy isolation and malformed saved report rejection.

Run `cd frontend && npm ci && npm test && npm run typecheck && npm run build` or review the same workflow jobs in GitHub Actions. Test against the intended saved reports and browsers before releasing.

No private market-data archive, credentials or broker tokens are stored by this feature.
