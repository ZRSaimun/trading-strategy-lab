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

## Two missing hours before the successor closes

The bullish/bearish synthetic regression also verifies that at the 25H boundary, an appended hour-25 candle has not closed and must not be read, even when hours 23 and 24 are missing. Its price, volume and minute-coverage accessors throw if touched. The as-of result must match the completed prefix and remain `RIGHT_CENSORED`, with no observed touch or live-trading eligibility. At a later completed boundary the missing slots may be classified `MISSING_HOUR` (as covered by the separate completed-successor tests). This is a timing/causality contract, not authenticated market coverage or performance evidence.

## 7 November 2026 — missing middle wait hour followed by a completed non-touch

`frontend/tests/hourly-fvg-middle-gap-later-no-touch.test.ts` adds mirrored synthetic bullish/bearish coverage where the first eligible wait hour is a completed non-touch, the next hour is absent, and a later completed candle also does not intersect the midpoint. The later non-touch cannot establish a complete first-touch history across the missing middle hour. At the later close, the result must remain `INCOMPLETE_WINDOW` / `MISSING_HOUR` with one missing slot and insufficient midpoint and verified-volume evidence. This is a causal archive-coverage regression only; no broker quotes, independently verified volume, fill or profitability evidence is supplied.

## Missing middle hour before successor close (8 November 2026)

The mirrored bullish/bearish regression in `frontend/tests/hourly-fvg-middle-gap-later-no-touch.test.ts` also appends a still-open hour-25 successor after a completed hour-23 non-touch and absent hour 24. At the hour-25 as-of boundary, all future OHLC, volume and coverage accessors must remain unread; the completed-prefix observation must be identical and `RIGHT_CENSORED`. Only a subsequently completed successor can establish `MISSING_HOUR` censoring. These synthetic tests establish causal handling, not broker-source authenticity, actual fills or profitability.

## 8 November 2026 — later completed wick does not undo earlier missing middle hour

The bullish and bearish synthetic middle-gap regressions now append a **completed midpoint-intersecting wick** after a completed non-touch successor, with an earlier unobserved hourly slot between formation and successor. Even after the later wick closes, the first-touch ordering is unknowable: the result must retain `INCOMPLETE_WINDOW` / `MISSING_HOUR` with one missing slot, no established first-touch close, insufficient midpoint/verified-volume evidence and no live-trading eligibility. The tests compare the already-censored prefix to the longer completed sequence. This only checks software censoring; it is not evidence of genuine quotes, authentic volume, fills or returns. See `frontend/tests/hourly-fvg-middle-gap-later-no-touch.test.ts`.

## 8 November 2026 — observed wait exposure excludes missing middle hours

The mirrored bullish/bearish middle-gap regression now also asserts that `firstTouchObservedWaitBars` remains exactly **one** after a completed first wait-hour non-touch, an absent second hour, and a later completed non-touch. The missing hour is not an observed no-touch or an additional at-risk observation; it remains an explicit `MISSING_HOUR` censor with one unknown slot. This is synthetic accounting integrity only, not evidence of a real session calendar, source continuity, broker fills or profitability.

## 8 November 2026 — censor time remains fixed after a later completed wick

The bullish/bearish missing-middle-hour regression also checks that a subsequently completed midpoint-intersecting wick cannot move the original `MISSING_HOUR` censor observation time (26H) or increase the observed pre-gap wait-bar count (one). A later price intersection cannot retrospectively certify the absent hour as a no-touch. These are synthetic causal accounting assertions, not independent quote or volume verification, execution evidence, or profitability.

## Still-open later wick after observed middle-hour gap (8 November 2026)

The bullish and bearish synthetic regression in `frontend/tests/hourly-fvg-middle-gap-later-no-touch.test.ts` now also appends a still-open later candle after a missing middle hour has already been exposed by a completed successor. At that candle's opening boundary, its OHLC, volume and minute-coverage getters must not be accessed; the entire as-of observation must match the completed prefix. The prior `MISSING_HOUR` censor timestamp and one genuinely observed wait bar remain unchanged. This is a causal isolation test only: source volume remains unverified, BID-only geometry is not a two-sided executable broker quote, and no profitability or live eligibility is established.

## Pending midpoint touch after an exposed middle-hour gap (8 November 2026)

`frontend/tests/hourly-fvg-middle-gap-pending-touch-isolation.test.ts` checks both bullish and bearish synthetic formations with a completed first wait-hour non-touch, missing middle hour and later completed non-touch. At the next hourly opening boundary, an apparent pending midpoint touch must not be inspected: all unrevealed OHLC, volume and coverage getters throw, and the entire as-of report must match the completed prefix. The earlier `MISSING_HOUR` censor remains fixed at 26H, with one observed wait bar and `NOT_EVALUATED` first-touch volume. This regression cannot authenticate a market closure, source identity, executable two-sided quotes, fill, or profitability. Keep research paper-only.

## Intrabar as-of timestamps fail closed (8 November 2026)

The mirrored pending-touch regression also supplies a half-hour as-of timestamp while an hourly candle is still open. The study rejects this non-hourly close boundary with `Invalid UTC hourly as-of close` before reading the pending candle's OHLC, volume or observed-minute accessors. A caller must supply a valid completed UTC hourly boundary, not reinterpret intrabar observations as completed hourly evidence. This is a synthetic input/timing contract, not independently verified broker quotes, market data or profitability.

## 8 November 2026 — nonfinite pending-hour timestamp is not missing evidence

The mirrored bullish/bearish pending-touch test now supplies a future candle with a `NaN` hour timestamp while preserving throwing OHLC, volume and coverage accessors through property descriptors (object spread would wrongly evaluate those getters). The study must reject the malformed timestamp rather than silently omit the row or inspect unrevealed prices. This is synthetic input-integrity coverage, not verified market-data provenance, broker execution, or profitability. Confirm exact-head CI before relying on the regression.

## 8 November 2026 — invalid future epoch values fail before price access

The mirrored pending-touch fixture now also rejects positive infinity, negative infinity, and an integer above JavaScript's maximum safe integer as future hourly opening timestamps. Property descriptors preserve deliberately throwing pending OHLC, volume and coverage getters, and the regression requires zero reads of those fields. These are malformed archive records, not missing hours or valid completed-bar evidence. The check does not authenticate broker quotes, source volume or profitability; keep the study paper-only.

## 8 November 2026 — additional malformed pending timestamp boundaries

The bullish/bearish pending-touch regression additionally rejects a fractional future UTC hourly opening timestamp (`26H + 0.5` seconds) and an integer below JavaScript's minimum safe integer. The same deliberately throwing future OHLC, volume and minute-coverage accessors must remain unread. This supplements positive unsafe integers and nonfinite values: an invalid row must never be treated as a missing observation or as a completed bar. These are synthetic input-integrity tests only; they do not verify actual source identities, volume receipts, broker BID/ASK execution, or profitability.

## Multiple future hours after a middle-hour gap (8 November 2026)

The bullish and bearish synthetic middle-gap regression now appends **two** unclosed hourly candles after the last completed as-of boundary. Both have throwing OHLC, volume and minute-coverage accessors. Neither can repair the earlier missing hour, manufacture a first midpoint touch, or change the completed-prefix observation; the test checks that no future evidence accessor executes. This is a no-lookahead software check, not authenticated broker quotes, source-classified volume, execution evidence or a profitability result.

## Malformed second pending hour (8 November 2026)

The bullish and bearish middle-gap regression also appends two not-yet-eligible hourly candles, with an invalid timestamp on the second. The as-of scan must reject the malformed archive without reading OHLC, volume or minute coverage from either pending candle. A valid two-hour pending suffix remains observationally identical to the completed prefix. These synthetic checks protect causal source-input integrity; they do not authenticate market data, prove midpoint fills or demonstrate profitability.

## 8 November 2026 — duplicate pending-hour timestamps

The mirrored synthetic middle-gap regression rejects two still-unclosed hourly candle records with the same UTC timestamp. Duplicate future rows are an invalid archive, not a reason to choose a preferred row or infer uninterrupted coverage. Both pending rows expose throwing OHLC, volume and minute-coverage accessors, which must not be read before rejection. This protects causal input integrity only; it supplies no authenticated broker BID/ASK quote, volume-source receipt, fill or profitability evidence. Keep the PR draft and check CI at the exact commit.

## 8 November 2026 — reversed future hourly archive ordering

The mirrored bullish/bearish middle-gap synthetic regression rejects two individually UTC-hour-aligned but reverse-ordered future hourly rows before reading either row's OHLC, volume or observed-minute accessors. Chronological ordering is required for a causal archive even when both rows are beyond the as-of boundary. This is an input-integrity test only; it does not establish broker data authenticity, first-touch fills or strategy profitability.
