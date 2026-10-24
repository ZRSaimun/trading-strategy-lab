# Structure research v3: causal closed-bar quality gate

The existing Research Charts `analyze()` detector now checks every input candle before confirming a swing, sweep, structure break or three-candle FVG. The new `validStructureSegments()` helper returns the first index of each uninterrupted valid candle run; `-1` means the candle cannot be used.

## Exact rules

- All timestamps must be finite safe UTC epoch seconds, nonnegative, within the JavaScript Date range, aligned to the selected timeframe, and strictly increasing inside a run.
- OHLC must be finite and internally consistent. Observed minutes must be positive integers.
- For 1m through 4H, the observed-minute count must equal the full expected number of minutes. A partial 5m bucket (4/5 observed minutes), for example, is not eligible for any structure event.
- Consecutive 1m through 1W buckets must be exactly one timeframe apart; monthly buckets must advance one UTC calendar month. The weekly anchor is Monday 00:00 UTC; monthly anchor is the first day at 00:00 UTC.
- Any invalid candle, duplicate, backwards timestamp or gap ends the active swing run. A newly valid candle starts a new run. Swing confirmation requires the entire left/right window to belong to that run, and a sweep or break requires the reference swing and trigger candle to be in the same run.
- An event's `observed_at` is the trigger candle close; no later candle may influence a prior event. The detector version is `structure-research-v3`.

## Limitations and intended conservatism

**Market closures are not exchange-calendar verified.** A weekend or holiday gap resets the run even if the closure is legitimate. This reduces questionable positives but also excludes potentially legitimate multi-session setups. Daily, weekly and monthly bars cannot establish every underlying constituent minute; the detector requires nonempty observations and calendar continuity only, not complete intraday coverage. Archive/source integrity and UTC-offset conventions must be established upstream. The gate is not an executable-quote validator and does not infer bid/ask spreads, volume reliability, news, margin, stops, or actual fills.

This change does **not** implement a full CRT/ICT entry/exit strategy, signal confirmation, broker order or backtest profitability claim. A rejected observation is **not** a losing trade. Previously saved reports or alert events should retain their original rule version; compare v2 and v3 only on identical source-isolated, timestamp-verified samples, with cost stress and untouched chronological holdout.

## Verification

```sh
cd frontend
npm ci
npm test
npm run build
```

The new `structure-quality.test.ts` includes deterministic tests for incomplete buckets, malformed OHLC, gaps, timestamp order, UTC month/week alignment, swing confirmation, sweep/break suppression, and prefix invariance. Full Docker and free-cloud smoke checks must pass in CI before any production-affecting merge. No database migration or production data mutation is required.
