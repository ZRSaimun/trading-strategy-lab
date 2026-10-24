# Within-window matched sweep baseline — retrospective research only

`frontend/lib/sweep-window-rematch.ts` implements `rematchSweepsWithinWindows()`, a pure, source-isolated companion to the v3 sweep outcome and historical UTC-hour baseline study in PR #17. It addresses a concrete weakness in post-hoc chronological filtering: when the original global matcher picks a control from an earlier development period, a later validation/holdout sweep is discarded even if a mature, same-hour **non-sweep control inside that later window** is available.

## Fixed protocol and controls

Before running, record the exact immutable dataset ID, provider, instrument/venue/price side, fixed UTC offset and evidence for that offset, 1m/1H/etc frame, v3 rule version, sweep swing lookback, horizon, assumed round-trip cost, matching seed, UTC boundaries and optional symmetric embargo. Do not select boundaries or seeds after looking at results. The three half-open windows are development, validation and retrospective holdout. Each is cut into a separate bar sample **before** matching. Controls come from the same sample, have the same UTC close-hour as their sweep and a complete label that matured before that sweep closed. Each control can be used only once in its window. A sweep or control whose outcome would require a candle beyond the window is not scored. Incomplete bars, unknown gaps, invalid prices and missing same-hour controls are excluded, never fabricated.

This procedure **re-matches** within each window rather than filtering globally chosen pairs after the fact. It is not interchangeable with the earlier `auditMatchedSweepsChronologically()`; report both for transparency. The latter exposes cross-window dependence in global matches, while this helper asks whether a within-window matched comparison can be constructed at all. This changes the historical comparator definition, so results must not be called an independent confirmation of the previous retrospective findings.

Each window reports sweep observations, matched and unmatched counts, pending outcomes, data-quality exclusions, unique event weeks, hypothetical mean net sweep/control bps and paired difference. A window with fewer than 30 pairs or 12 event weeks is labelled `INSUFFICIENT_EVIDENCE`; otherwise it is **`EXPLORATORY_ONLY`**, not significant or profitable. The code never places broker orders or reads credentials.

## Interpretation and remaining work

The split named "holdout" is **not untouched**: earlier research already examined the available archives and the procedure was designed after inspecting previous results. Using pre-window historical swing references to form a current signal is causal, but pre-window controls are intentionally forbidden. Repeated tuning of boundaries, seeds, direction, horizons or costs would create selection bias. The comparator matches only UTC hour, not volatility, weekday, macro news, market regime, spread or contract characteristics. Timezone conventions for the source ZIPs remain unverified. BID-only historical candles cannot determine executable fills, slippage, commissions, CFD financing, margin, borrow fees or true stop-loss risk. Overlapping events are dependent; no p-value or forward profitability claim is supplied.

The next independent evaluation should lock a prospective protocol and use newly arriving, authenticated source-identified completed candles, with source-specific broker costs and actual paper fills. Do not merge/deploy this branch without verified latest-head CI and a verified production backup/rollback procedure.

## Tests

```sh
cd frontend
node --experimental-strip-types --test tests/sweep-window-rematch.test.ts
npm test
npm run build
```

Eight deterministic synthetic tests cover within-window re-matching, strict label boundaries, embargo, incomplete controls, deterministic and input-order-invariant matching, future append stability, invalid timestamps and parameters, and rejection of invalid event versions. These are **software behavior tests**, not historical profitability evidence.
