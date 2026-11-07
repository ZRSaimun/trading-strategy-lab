# Completed-hour bearish FVG evidence isolation

The standalone 1H FVG research treats a bearish first midpoint intersection as observable only after the intersecting hourly BID candle closes. The synthetic regression `frontend/tests/hourly-fvg-bearish-postclose-isolation.test.ts` records the first-touch result at its 24H close and verifies that appending a still-open future candle cannot change that earlier as-of result or read the future candle's OHLC, volume or minute-coverage fields. The completed-prefix full-history result must agree with the same as-of result.

The synthetic touch reports unusually large volume, but its declared source is **unverified**. Therefore `SOURCE_UNVERIFIED` and `INSUFFICIENT_DATA` remain mandatory and `eligibleForLiveTrading` remains false. This is a causal software regression, not independent validation of source identity, real volume, broker BID/ASK quotes, spread, fill probability or trading profitability. No orders, private datasets, credentials or deployment are involved.

## Bullish symmetry regression

`frontend/tests/hourly-fvg-bullish-postclose-isolation.test.ts` mirrors the post-close isolation check for a completed bullish gap and first midpoint touch. It compares the completed-prefix study with an as-of scan containing a later still-open candle whose OHLC, volume and observed-minute getters must never run. Unverified high reported volume remains insufficient evidence, and the study cannot authorize live trading. Both direction checks use synthetic BID-only prices; neither authenticates broker quotes, demonstrates an executable midpoint fill or measures profitability.

## Missing first eligible hour

The synthetic regression `frontend/tests/hourly-fvg-first-wait-gap-censor.test.ts` checks a bullish formation followed by a missing first eligible hourly BID bar and a later completed midpoint-intersecting bar. The later touch cannot erase the unknown earlier hour: the first-touch outcome stays `INCOMPLETE_WINDOW`, with `MISSING_HOUR` censoring observable only when the later bar closes. This prevents treating a discontinuous archive as a complete first-touch opportunity or a verified no-touch. It is not a broker execution or profitability test.

## Bearish first-eligible-hour gap censoring (7 November 2026)

A synthetic bearish formation with an unobserved first eligible hourly candle remains right-censored until a later completed candle exposes the gap. Even when that later candle's wick crosses the midpoint, it cannot establish the *first* touch: the study must report `INCOMPLETE_WINDOW`, `MISSING_HOUR`, one missing hour, and insufficient midpoint/verified-volume evidence. Regression: `frontend/tests/hourly-fvg-bearish-first-wait-gap-censor.test.ts`. This is a software causal-integrity check, not proof of source completeness, broker fills or profitability.

## 7 November 2026 — missing first hour followed by a non-touch

Synthetic bullish and bearish tests now cover a missing first-eligible 1H candle followed by a *completed non-touch* candle. The later no-touch is not proof that the missing hour also did not touch: the observation remains `INCOMPLETE_WINDOW` / `MISSING_HOUR`, with one missing slot and insufficient midpoint and independently verified volume evidence. This is a conservative causal censoring check only; it cannot establish authentic market coverage, executable broker BID/ASK prices, or profitability. Check exact-head CI separately.

## 7 November 2026 — still-open successor cannot repair a missing hour

The bullish/bearish missing-first-hour regression also appends a later, **not-yet-closed** hourly candle whose price, volume and minute-coverage getters deliberately throw if evaluated. At the last completed-hour boundary, the causal result must equal the observed-prefix result and remain right-censored; only a subsequently *closed* candle may expose the missing slot and change the censor reason to `MISSING_HOUR`. The test protects against future-field access, not against source tampering or incomplete broker data. No trading permission or profitability is implied.

## Two missing hours and a later completed non-touch

The bullish/bearish synthetic regression now also covers two consecutive absent first-eligible hourly bars (hours 23 and 24), followed by a completed non-touch at hour 25. The first-touch window remains `INCOMPLETE_WINDOW` with `MISSING_HOUR`, exactly two missing slots and no observed first-touch close. The censor reason is observed only at hour 26's completed boundary. This distinguishes a later observed non-touch from an uninterrupted sequence of observed non-touches. Unverified volume and missing broker quotes remain insufficient; no profitability or live eligibility is established. Test: `frontend/tests/hourly-fvg-missing-first-hour-later-no-touch.test.ts`.
