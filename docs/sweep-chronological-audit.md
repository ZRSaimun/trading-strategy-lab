# Chronological matched-sweep audit (research only)

`frontend/lib/sweep-chronological-audit.ts` provides a pure, source-isolated `auditMatchedSweepsChronologically()` helper for the pre-existing `MatchedSweepComparison` produced by the v3 sweep/matured-control study in PR #17. It **does not place trades, optimize parameters, prove a trading edge or produce an untouched holdout**.

## Fixed protocol

Before examining outcomes, record the exact source dataset ID, instrument, timeframe, provider/price side, declared UTC offset, v3 rule version, matching seed, fixed-horizon and assumed round-trip costs. Supply four explicit UTC epoch-second boundaries: `developmentStartUtc < developmentEndUtc < validationEndUtc < holdoutEndUtc`. The windows are half-open: `[developmentStartUtc, developmentEndUtc)`, `[developmentEndUtc, validationEndUtc)`, `[validationEndUtc, holdoutEndUtc)`.

A matched sweep is counted only if its observation, entry and exit are inside the same window, and its unique historical control's observation and entry are also inside that window. A control's outcome must have matured before the sweep observation. Pairs whose control belongs to an earlier window are **excluded** rather than reusing a development label in validation or holdout. Sweeps whose labels cross a window end are purged. Optional symmetric `embargoSeconds` excludes observations near the start and labels near the end. The audit reports separate exclusion counts and mean hypothetical net basis-point outcomes for each window.

The helper rejects invalid boundaries, nonfinite returns, forged differences, future-referencing control outcomes, duplicate sweeps/controls, mismatched direction and overflow. It preserves the input and is invariant to input pair order. With fewer than 30 matched pairs or 12 event weeks, each window reports `INSUFFICIENT_EVIDENCE`; above that it reports `EXPLORATORY_ONLY`, **not** statistically significant or profitable.

## Interpretation limits

The matched pairs have already been selected on historical data. Calling the last segment “holdout” does **not** make it untouched after inspecting that period, selecting seeds or iterating on rules. A genuinely untouched prospective test requires freezing the full research protocol and testing subsequent unseen data. Excluding earlier controls may leave sparse or unrepresentative late-window samples. Week counts do not account for serial correlation or overlapping outcomes. The audit does not adjust for multiple hypotheses or validate the HistData source timezone. BID-only candles cannot establish actual spreads, slippage, overnight CFD financing, broker fills or stop-loss performance. This is a diagnostic, not a strategy or live trading signal.

## Tests

```sh
cd frontend
node --experimental-strip-types --test tests/sweep-chronological-audit.test.ts
npm test
npm run build
```

Seven deterministic synthetic tests cover split assignment, cross-window control exclusions, label purging and embargo, chronology, duplicate/forged data, order invariance, insufficient sample flags and overflow. No private archives, credentials or external market-data requests are required.
