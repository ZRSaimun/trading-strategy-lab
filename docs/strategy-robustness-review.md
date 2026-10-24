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

## Verification
`frontend/tests/research-review.test.ts` covers return reversal, small holdouts, drawdowns, no-trade cases, missing segments, source uncertainty, strategy isolation and malformed saved report rejection.

Run `cd frontend && npm ci && npm test && npm run typecheck && npm run build` or review the same workflow jobs in GitHub Actions. Test against the intended saved reports and browsers before releasing.

No private market-data archive, credentials or broker tokens are stored by this feature.
