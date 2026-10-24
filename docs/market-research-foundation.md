# Research priorities for Gold, Nasdaq and oil

Verified source references, 24 October 2026:

- HistData FAQ: https://www.histdata.com/f-a-q/ — bar data are insufficient to reconstruct tick spreads; ask prices are in Generic ASCII tick files. Source time is fixed EST without DST.
- CFTC WTI report announcement: https://www.cftc.gov/PressRoom/PressReleases/8315-20 — May 2020 WTI settled at -37.63 on 20 April 2020. This is a particular expiring contract, not evidence that an arbitrary WTI CFD used the same prices.
- CME negative-price support notice: https://www.cmegroup.com/notices/clearing/2020/04/Chadv20-160.html — energy systems support zero/negative prices.

Engineering implication: reject invalid OHLC and nonfinite numbers, but do not apply a universal positive-price filter. Added regression tests for valid negative OHLC, corrupt archives and bounded quarantine samples. These are synthetic tests, not market observations.

## Required order

1. Establish immutable original archives and exact instrument/provider/quote-side identities. NSXUSD must not inherit NDX cash or NQ futures execution assumptions. Contract expiry and roll transformations must be explicit for futures.
2. Build provider-aware append storage with collision quarantine and transactional checkpoints before production backfill. Existing replacement importer remains unsuitable for cumulative ingestion.
3. Verify real archive manifests, timezone conversion, database recovery, millions-row import/query performance and chart completeness. No original archives are currently available in this conversation.
4. Reproduce A–E against the same validated dataset, risk budget and execution assumptions. Compare zero-cost, stated-cost and stressed-cost runs; label assumed spreads rather than presenting reconstructed bid/ask fills.
5. Establish forecasting baselines: no-change price forecast, training-only direction frequency, regularized logistic direction model and simple volatility estimate. Evaluate 5m, 15m, 1h and session labels separately. Prices must be available at forecast time; overlapping labels require purging/embargo. Standardization and feature selection fit training data only.
6. Compare candidate models on chronological walk-forward folds with a final protected period. Use Brier/log loss, calibration, return forecast error, net expectancy, drawdown and uncertainty. Record every attempted model to expose selection effects. A model beating classification accuracy alone does not establish tradable profit.
7. Add publication-time economic event records and forward paper forecasts. Evaluate drift and calibration before retraining; never replace a model merely because the latest fitted backtest looks better.

No predictive accuracy or profitable strategy has been demonstrated. Historical backfill needs the actual files; production acceptance needs the correct Supabase and Render access. No new paid service, live order interface or production change is required for the next local development steps.
