# Revealed replay evidence

Research Charts → Start candle replay displays a read-only evidence panel in the existing inspector, in both browser-local and authenticated modes. It receives only `visibleCandles`, the same prefix used by chart observations. Advancing or rewinding recomputes the window; unseen future candles do not contribute to counts.

The panel reports the exact source label, full imported-dataset SHA-256, timeframe, revealed bar count, first/last opening timestamps in UTC, reported observed-minute total, unusable structural bars and run breaks. Opening timestamps are explicitly not signal observation times or broker fill times. It reuses `validStructureSegments`, preserving existing completed-bar quality gates: incomplete intraday candles, malformed OHLC/coverage and discontinuities cannot certify a continuous prefix. Unknown gaps are not assumed to be exchange closures. Daily/weekly/monthly coverage remains uncertified. `OBSERVED_PREFIX` describes the structural diagnostic only, never a trade permission; source fields may remain unavailable.

The minute total sums only positive safe-integer supplied counts, including valid counts on otherwise unusable bars. It is not elapsed time or proof of full coverage. Run breaks count starts of subsequent valid runs, including recovery after invalid bars, not the number of missing minutes. No missing candles are synthesized.

The displayed dataset hash identifies the complete imported source snapshot, including unrevealed history; it is not a prefix hash, independently authenticated source receipt or verified broker quote. Existing source metadata elsewhere may describe the full import. This panel does not alter alerts, detection timing, simulator eligibility, storage, broker-specific CFD costs, or paper-only controls. Spread, financing, slippage, news, volume authenticity and profitability are not evaluated here.

## Reference review

Reviewed [Jake Schincariol's day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill) at `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`, including README, MIT LICENSE (copyright 2026 Jake Schincariol), and `trader-timemachine/SKILL.md`. Useful workflow ideas are explicit replay inputs, reproducibility, completed-bar exclusions and distinguishing simulation from prediction. This change is original implementation of an inspectable replay evidence summary; no upstream code, market fixtures, broker workflow, unofficial feeds or performance claims are copied. Its stock/session assumptions and simplified gap/stop costs are not suitable defaults for this application's broker-specific CFD research.

## Regression checks

`node --experimental-strip-types --test tests/replay-evidence.test.ts` covers empty state, prefix stability under future mutation, rewind, partial coverage, unknown gaps, malformed data, duplicate times and calendar-month adjacency. Full frontend tests and production build remain required before review.
