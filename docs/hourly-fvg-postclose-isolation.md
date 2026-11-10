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

## 8 November 2026 — safe opening with unsafe completed close

The mirrored bullish/bearish pending-hour regression now supplies an hour-aligned future opening timestamp that is itself a JavaScript safe integer, but whose computed hourly close is not. The as-of scan must reject the row without reading its unrevealed OHLC, volume or minute-coverage getters. A safe opening alone is insufficient when downstream observations use close epochs. This synthetic boundary test does not verify authentic broker data, execution or profitability.

## 8 November 2026 — source-declared exchange volume cannot resolve a missing hour

The bullish/bearish middle-hour gap fixture is rerun with `volumeType: 'exchange'` and `volumeVerified: true` **as caller-supplied declarations only**. Even under that stronger declared volume classification, the missing first-touch wait hour remains `INCOMPLETE_WINDOW` / `MISSING_HOUR`; only one completed wait hour was observed, first-touch volume stays `NOT_EVALUATED`, verified-volume evidence is `INSUFFICIENT_DATA`, and live eligibility remains false. This regression prevents source labels from overriding temporal coverage. It does **not** authenticate exchange-volume identity, data licensing, broker BID/ASK fills, or profitability.

## 8 November 2026 — declared exchange volume cannot reveal future hours

The mirrored middle-gap regression additionally checks the as-of result with two unclosed future hourly candles while the caller claims `volumeType: 'exchange'` and `volumeVerified: true`. The result must match the completed-prefix observation exactly, without reading future OHLC, volume, or minute-coverage getters. A source label is not an independently verified receipt and cannot bypass the completed-hour boundary or repair the missing middle hour. This synthetic assertion does not establish executable broker quotes, authenticated volume, fills, or profitability.

## 8 November 2026 — future timestamp cannot rewrite completed OHLC

The mirrored bullish/bearish middle-gap regression supplies a future hourly `time` accessor that mutates an already completed candle's close while the as-of scan reads its timestamp. The study must reject the revised completed-row descriptor rather than return a result computed from an inconsistent historical snapshot. The future row's OHLC, volume and observed-minute accessors remain unread. This is a synthetic mutation-isolation regression; it neither authenticates BID/ASK quotes nor establishes volume provenance, broker execution or profitability. Keep draft, paper-only, unmerged and undeployed; verify the exact commit's CI before treating the regression as passing.

## 8 November 2026 — future timestamp cannot rewrite completed volume or coverage

The mirrored bullish/bearish synthetic middle-gap regression extends the historical-snapshot mutation guard beyond completed OHLC: a future candle's timestamp getter attempts to revise either a completed candle's `volume` or `observed_minutes` while the as-of archive is being preflighted. Both cases must fail closed before accessing the future candle's unrevealed OHLC, volume, or coverage. The test asserts the getter runs exactly once and no future market-evidence accessor runs. This validates a software integrity boundary, not independent volume-source authentication, genuine two-sided broker quotes, fills, or profitability. Keep draft, paper-only, unmerged and undeployed; verify exact-head CI.

## 8 November 2026 — future timestamp cannot retime completed source evidence

The mirrored bullish/bearish synthetic middle-gap regression now supplies a future candle's timestamp getter that attempts to rewrite an already completed hourly candle's `time` field. The causal as-of scan must reject the changed historical snapshot, without reading the future candle's OHLC, volume or minute-coverage accessors. A completed bar's identity cannot be revised by a later, unclosed row. This is a software mutation-integrity check, not independently authenticated quotes, volume provenance, observed broker execution or profitability. Keep paper-only and verify exact-head CI.

## 8 November 2026 — completed opening-price snapshot isolation

The mirrored bullish/bearish synthetic regression additionally checks that an unclosed future candle's timestamp getter cannot rewrite the `open` of an already completed candle. The as-of scanner must reject the inconsistent snapshot without reading the future candle's OHLC, volume or observed-minute accessors. This is a fail-closed software integrity assertion, not evidence of authenticated source identity, executable quotes, or profitability. Keep the draft PR unmerged and check exact-head CI before claiming the regression passes.

## 8 November 2026 — completed high/low snapshot isolation

The mirrored bullish/bearish pending-hour synthetic regression now also attempts to mutate each completed candle's `high` and `low` independently from a future row's timestamp getter. The as-of scanner must reject both changes before reading any future OHLC, volume or observed-minute evidence. This closes the remaining price-extreme fields in the completed-snapshot mutation test matrix; it does not authenticate source quotes, actual broker execution, volume provenance or trading returns. Keep the PR draft and verify exact-head CI.

## 8 November 2026 — completed evidence descriptor replacement

The mirrored bullish/bearish pending-hour regression now checks that a future candle timestamp getter cannot replace a completed candle's ordinary `close` data property with a getter, even one returning the unchanged numeric value. The causal as-of scanner must reject the descriptor change without executing that completed-price getter or any future OHLC, volume, or minute-coverage getter. This is in-process schema integrity, not independently authenticated volume, broker BID/ASK execution, observed fills, or profitability. Keep draft, paper-only and verify exact-head CI.

## 8 November 2026 — completed volume and coverage accessor substitution

Mirrored bullish/bearish synthetic tests now check that an unclosed future hourly timestamp accessor cannot replace a previously completed candle's plain `volume` or `observed_minutes` field with a getter, even when the getter would return the original value. The as-of scanner must reject the descriptor mutation without invoking the substituted getter or reading any future OHLC, volume, or coverage accessors. This protects the completed evidence schema; it does not authenticate a provider, supply genuine BID/ASK quotes, or demonstrate trading profitability. The exact-head CI result must be checked separately; keep draft, paper-only, unmerged, and undeployed.

## 9 November 2026 — completed evidence field deletion during future preflight

Mirrored bullish/bearish synthetic regressions now attempt to delete a completed candle's `close`, `volume`, or `observed_minutes` while an unclosed future candle's timestamp is being inspected. The causal as-of study must reject the changed historical snapshot without accessing future OHLC, volume, or coverage getters. This checks fail-closed in-memory schema integrity only: no independent source authentication, genuine broker BID/ASK execution, licensed historical validation, or profitability evidence is supplied. Keep the PR draft, paper-only, unmerged and undeployed; verify CI against the exact new head.

## 9 November 2026 — completed timestamp descriptor substitution

Mirrored bullish/bearish synthetic tests now cover an unclosed future candle's timestamp getter replacing an already completed candle's plain `time` value with a getter that would return the identical epoch. The causal as-of scanner must reject this historical-schema mutation **without executing** the substituted completed timestamp getter or reading any future OHLC, volume, or minute-coverage accessors. Equal numeric values do not make an altered source representation immutable. This checks local software integrity only; it does not verify independently authenticated source identity, broker BID/ASK quotes, first-touch execution, licensed holdout data, or profitability. Keep draft, paper-only, unmerged, and undeployed; verify exact-head CI separately.

## 9 November 2026 — completed OHLC descriptor isolation matrix

The mirrored bullish/bearish synthetic regression additionally rejects an unclosed future timestamp accessor that substitutes a getter for a completed candle's `open`, `high`, or `low` data property, even when the getter would return the original numeric value. The substituted completed getter and the future candle's unrevealed OHLC, volume and minute-coverage getters must remain unread. This completes the completed-OHLC accessor-substitution coverage alongside `close`; it is not an authenticated source receipt, fill observation, or profitability result. Keep draft and verify the new exact-head CI separately.

## 9 November 2026 — completed opening/extreme deletion guard

The mirrored bullish/bearish synthetic pending-touch regression now deletes each of a previously completed candle's `open`, `high`, and `low` fields in turn from a still-open future candle's timestamp getter. The causal as-of preflight must reject the changed completed snapshot without consulting any unrevealed future OHLC, volume, or observed-minute getter. This closes the deletion coverage alongside existing `close`, volume, and minute-coverage checks. It tests archive integrity only: neither source authenticity, real BID/ASK fills, nor profitability is established. Verify the new exact-head CI independently before treating the regression as passing.

## 9 November 2026 — completed evidence descriptor-flag stability

The mirrored synthetic bullish/bearish pending-hour regression now checks that a still-open future candle's timestamp accessor cannot silently change a previously completed candle's `enumerable` or `writable` descriptor flag on any of `time`, OHLC, `volume`, or `observed_minutes`, even when the underlying numeric value stays unchanged. The as-of study must reject the changed historical snapshot without reading future market fields. This protects archive-schema integrity only: it does not authenticate volume, establish a broker fill, or prove profitability. Keep the research paper-only and verify the exact-head CI before treating the regression as passing.

## 9 November 2026 — completed field configurability integrity

The mirrored bullish/bearish synthetic pending-hour regression now also rejects a still-open future timestamp accessor changing the `configurable` descriptor of any completed `time`, OHLC, `volume`, or `observed_minutes` field while leaving its numeric value intact. Together with the existing enumerable/writable checks, this covers all three ordinary data-property descriptor flags. Future unrevealed OHLC, volume and coverage getters remain forbidden. This is an archive-integrity regression, not independently authenticated source data, broker execution, a trading signal, or profitability evidence. Verify exact-head CI separately; keep draft, paper-only, unmerged and undeployed.

## Completed archive-slot replacement during future timestamp preflight (9 November 2026)

Mirrored synthetic bullish/bearish tests now replace a previously completed hourly candle **array slot** while a still-open future candle's timestamp is read. The as-of study must reject this changed row identity even if the original completed row's property descriptors remain unchanged; future OHLC, volume and observed-minute accessors must remain unread. This is a fail-closed archive-integrity regression, not independent source authentication, executable BID/ASK midpoint-fill evidence or a profitability claim. Check the new exact-head CI before treating the regression as verified.

## 9 November 2026 — equivalent completed-row replacement

The mirrored bullish/bearish pending-hour regression now rejects replacement of a previously captured completed candle's array slot with a **new object holding identical field values**. This checks completed-prefix row identity separately from numeric changes and property-descriptor mutation. The still-open candle's OHLC, volume and observed-minute getters must remain unread. This is synthetic source-integrity coverage, not verified broker data, trading execution, or profitability. Verify CI for the exact commit; keep the PR draft, paper-only, unmerged and undeployed.

## 9 November 2026 — repair TypeScript build for hostile getter regression

The equivalent completed-row replacement fixture deliberately uses future market-field getters that only throw, so TypeScript infers `void` rather than numeric candle fields. The fixture now casts through `unknown` before the `Bar` test type; runtime behavior, assertions and production strategy code are unchanged. Previous exact-head CI #42580126545 failed frontend, Docker and free-cloud build jobs at TS2352 (test line 403), while 1,114 frontend tests and the three backend/PostgreSQL jobs passed. Recheck CI on the repair commit; the earlier failure is not evidence of a trading result. Remains draft, paper-only, unmerged and undeployed.

## 9 November 2026 — completed-hour order cannot change during pending timestamp preflight

Mirrored bullish/bearish synthetic regressions now swap two already-completed hourly archive rows from a still-open future candle's timestamp accessor. The causal as-of FVG study must reject this mid-scan historical reorder, rather than treating the modified sequence as the original completed prefix, and must not read the future candle's unrevealed OHLC, volume or observed-minute fields. This protects archive identity and causal ordering only; it does not authenticate real quotes, volume provenance, broker execution or profitability. Exact-head CI must be checked separately; remain draft, paper-only and undeployed.

## Completed archive index visibility regression (9 November 2026)

A synthetic still-open future candle's timestamp getter can attempt to make an already-completed hourly archive index non-enumerable after the completed prefix is captured. The bullish and bearish regression cases require the causal as-of scan to reject the changed archive shape without reading future OHLC, volume, or minute-coverage accessors. This is a source-integrity assertion, not evidence of an executable broker quote, authenticated volume, or trading profitability. CI must be checked against the exact new commit.

## 9 November 2026 — completed archive slot writability

Mirrored bullish/bearish synthetic regression cases now require the causal 1H FVG as-of scan to reject a still-open candle's timestamp getter changing a completed archive index from writable to non-writable. The row and its numeric fields are unchanged, but the captured array-slot descriptor is no longer the same historical evidence. The regression also requires that no future OHLC, volume, or observed-minute getter executes. This complements the archive-index visibility regression; it is not an authenticated volume receipt, executable broker quote, or profitability result. Verify CI on the exact new head before treating this assertion as passing. Remain draft, paper-only, unmerged and undeployed.

## 9 November 2026 — completed archive slot configurability

Mirrored bullish/bearish synthetic tests now reject a still-open future hourly candle's timestamp getter making a captured completed archive index non-configurable. The indexed row and its OHLC/volume/coverage values remain unchanged, but the historical array-slot descriptor has changed. The causal as-of scanner must fail closed without invoking any future OHLC, volume or observed-minute getter. This completes the ordinary index descriptor-flag regression matrix alongside enumerability and writability; it does not authenticate source identity, volume, broker quotes or trading performance. Check exact-head CI before claiming the new test passes. Keep draft, paper-only, unmerged and undeployed.


## 9 November 2026 — pending timestamp cannot truncate completed archive

Mirrored bullish/bearish synthetic regressions attempt to shorten the hourly source array while an unclosed future candle's timestamp accessor is evaluated. The causal as-of study must reject removal of previously captured completed rows without consulting any future OHLC, volume, or observed-minute fields. This is an in-memory archive-integrity test only, not authenticated quote or volume evidence, fill validation, or proof of profitability. Keep draft and verify the exact new head in CI before claiming the regression passes.

## 9 November 2026 — sparse completed-hour deletion guard

Mirrored synthetic bullish/bearish tests now delete an already captured completed hourly archive index from a still-open future candle's timestamp getter, leaving the array length unchanged. The causal as-of scan must fail closed on this sparse historical archive instead of interpreting the deleted hour as an observed no-touch, and must never inspect the future candle's unrevealed OHLC, volume or minute-coverage fields. This checks in-memory source integrity only; it does not authenticate a broker feed, prove first-touch execution, or demonstrate returns. Confirm exact-head CI separately. Paper-only, no deployment.

## 9 November 2026 — reject appended backdated completed-hour evidence

Mirrored bullish/bearish synthetic regressions now check that an unclosed future candle's timestamp getter cannot append a backdated completed-hour row after the source archive was captured. Such a row is not part of the original as-of evidence even when its timestamp is earlier than the evaluation boundary. The scan must reject the mutated archive without reading the future candle's OHLC, volume or observed-minute getters. This is causal source-integrity coverage only, not real broker data, executable fills or trading profitability. Verify the new exact-head CI; keep draft, paper-only, unmerged and undeployed.

## 9 November 2026 — pending timestamp cannot splice completed archive history

Mirrored bullish/bearish synthetic regressions insert a duplicate completed-hour object into the middle of the captured archive from a still-open candle's timestamp getter. Unlike an append, this shifts completed row indices; the causal as-of 1H FVG study must reject the changed historical source without reading any unrevealed future OHLC, volume, or observed-minute getter. This is an in-memory archive integrity test only, not independently verified market data, broker fills, or profitability. Exact-head CI must pass before considering the change verified. Keep draft, paper-only, unmerged and undeployed.


## 9 November 2026 — pending timestamp cannot reverse completed chronology

Mirrored bullish/bearish synthetic regressions now attempt to reverse the captured hourly archive from a still-open future candle's timestamp getter. The causal as-of 1H FVG study must reject this changed chronology rather than silently accepting rearranged completed evidence, and must not read future OHLC, volume, or observed-minute accessors. This is an in-memory integrity assertion, not an authenticated source receipt, broker execution test, or profitability evidence. Exact-head CI remains authoritative; keep the PR draft, paper-only, unmerged and undeployed.

## 9 November 2026 — pending timestamp must not revise completed volume

Mirrored bullish/bearish synthetic regressions now check that reading an unclosed future hour's timestamp cannot rewrite the numeric volume of a previously captured completed-hour candle while preserving timestamps and archive indices. The causal as-of scanner must fail closed and must not read the future candle's OHLC, volume or observed-minute accessors. This protects the integrity of the completed source snapshot; it **does not** verify the source classification, exchange/broker provenance, or trading profitability. Run exact-head CI before considering the regression verified. Keep draft, paper-only, unmerged and undeployed.

## 9 November 2026 — completed close cannot be revised by pending timestamp

Mirrored synthetic bullish/bearish tests assert that a still-open hour's timestamp getter cannot change an already captured completed candle's `close` while retaining its time, position and volume. A revised close could alter the historical FVG or midpoint-rejection decision; the as-of scanner must reject the archive mutation without reading future OHLC, volume or observed-minute fields. This is a causal integrity regression, not an authenticated market-data or profitability result. Verify exact-head CI before considering it passing; keep draft, paper-only and undeployed.

## 9 November 2026 — completed minute-coverage evidence cannot be revised

Mirrored bullish/bearish synthetic regressions now require the causal 1H FVG as-of scan to reject a still-open future candle timestamp accessor changing a captured completed-hour `observed_minutes` value from 60 to 59 while keeping its OHLC, volume, timestamp and archive slot unchanged. The pending candle's future OHLC, volume and minute-coverage accessors must not execute. This prevents retroactive completeness changes from silently altering first-touch eligibility. This is only an in-memory causal-integrity assertion, not authenticated market coverage, executable broker quotes, or profitability. Verify exact-head CI before claiming a pass; keep draft, paper-only, unmerged and undeployed.

## 9 November 2026 — direction-specific completed-close revision fixture

The mirrored completed-hour close-mutation regression now changes the bullish fixture's closed candle from 100 to 100.5 and the bearish fixture's closed candle from 101 to 101.5, rather than assigning both directions the same replacement close. Both cases must reject the changed captured archive before accessing any unclosed future market fields. These are synthetic integrity tests only; they do not establish real broker data provenance, trading edge or profitability.

## 9 November 2026 — completed wick extremes are immutable during pending-hour preflight

Mirrored bullish/bearish synthetic tests now check both `high` and `low` independently: an unclosed future hourly candle's timestamp getter cannot rewrite an already captured completed-hour wick while leaving its timestamp, other prices, volume and minute coverage intact. Such a revision could change a historical midpoint-touch decision. The causal as-of FVG scanner must reject the altered completed archive without reading any future OHLC, volume or coverage getter. This tests snapshot integrity, **not** actual broker BID/ASK fills, authenticated volume provenance, or trading profitability. Verify CI against the exact new head before claiming success; remain draft, paper-only, unmerged and undeployed.

## 10 November 2026 — completed timestamp value cannot change during pending-hour preflight

Mirrored bullish/bearish synthetic tests now require the causal 1H FVG as-of scanner to reject a still-open future candle's timestamp accessor rewriting a previously completed candle's numeric `time` from hour 23 to hour 22. The completed row remains in the same array slot with unchanged OHLC, volume and minute coverage; no future OHLC, volume or coverage getter may run. This closes the in-place completed-field revision matrix alongside OHLC, volume and coverage. It checks causal archive integrity only, not authenticated market data, broker execution or profitability. Keep draft and paper-only; verify exact-head CI independently.

## 10 November 2026 — pending timestamp cannot truncate completed archive

Mirrored synthetic bullish/bearish regression verifies that a future timestamp getter cannot shorten the captured completed-hour array during as-of preflight. Reject altered historical source length before reading any unclosed OHLC, volume or minute-coverage getter. This is a source-integrity test only, not independently authenticated quotes, executable fills or profitability.

## 10 November 2026 — unreadable pending timestamp fails closed

`frontend/tests/hourly-fvg-unreadable-future-timestamp.test.ts` checks bullish and bearish completed 1H FVG prefixes with a subsequent unclosed candle whose timestamp getter throws. The as-of scan must propagate the timestamp-read failure rather than silently omit the row or reinterpret the source as a complete archive; it must not inspect the pending candle's OHLC, volume or coverage. This is synthetic source-integrity testing only, not verified volume, broker BID/ASK execution, or profitability. Verify exact-head CI before relying on the regression.

## 10 November 2026 — malformed pending-hour timestamp cannot be silently skipped

`frontend/tests/hourly-fvg-invalid-pending-timestamp.test.ts` exercises mirrored bullish/bearish synthetic archives with a pending candle whose timestamp is NaN, positive/negative infinity, fractional-hour, non-aligned integer or negative zero. Each must fail closed during as-of timestamp preflight, even though its OHLC, volume and observed-minute fields are deliberately unreadable. No pending market getter may run. This is an archive-integrity regression only; it neither authenticates source volume nor establishes broker BID/ASK fills or profitability. Keep this PR draft, paper-only, unmerged and undeployed pending exact-head CI.

## 10 November 2026 — pending timestamp cannot rewrite source declarations

`frontend/tests/hourly-fvg-pending-source-rewrite.test.ts` adds four synthetic regressions (bullish/bearish × provider identity/volume-verification flag). A not-yet-completed candle's timestamp accessor attempts to alter previously captured source provenance. The causal as-of scan must fail closed rather than export a report with a changed provider or a newly asserted verification flag; the future candle's OHLC, volume and minute-coverage getters remain unread. These tests exercise internal snapshot consistency only. Caller-supplied `volumeVerified` is **not** independent authentication of volume or feed identity; no broker quotes, fills, return estimates or live-trading authorization are established.

## 10 November 2026 — pending timestamp cannot rewrite dataset lineage hashes

`frontend/tests/hourly-fvg-pending-lineage-rewrite.test.ts` covers bullish/bearish synthetic completed-hour prefixes and attempts to replace either the captured `datasetId` or `archiveSha256` with a different, syntactically valid 64-character hash while reading the timestamp of a still-open successor. The causal as-of study must reject the changed declaration snapshot before accessing that successor's OHLC, volume or minute-coverage fields. A well-formed hash is not an independently verified source receipt, and these regressions do not authenticate prices, volume, broker fills or profitability. Keep draft and paper-only; verify the exact commit's CI before claiming success.

## 10 November 2026 — pending-hour source instrument, side and volume type remain fixed

`frontend/tests/hourly-fvg-pending-instrument-side-volume-type.test.ts` adds six mirrored bullish/bearish synthetic regressions. A still-open future hourly candle's timestamp accessor tries to rewrite the captured instrument identity, BID/ASK side or volume classification. The as-of 1H FVG scanner must reject each declaration mutation without inspecting future OHLC, volume or observed-minute getters. These checks protect snapshot consistency; they do not independently verify source identities, volume receipts, two-sided broker quotes, fills or profitability. Keep draft and paper-only, and verify exact-head CI before treating the new tests as passing.

## 10 November 2026 — future timestamp cannot extend archive length

`frontend/tests/hourly-fvg-pending-append.test.ts` adds mirrored bullish/bearish synthetic cases where a still-open future candle's timestamp getter appends an additional archive row during the as-of scan. The completed-prefix scan now rejects a changed archive length before accepting results; no pending OHLC, volume or minute-coverage getters may run. This guards against silently ignoring an appended source row because the original archive length was captured earlier. The test is not independently authenticated source, broker execution, or profitability evidence. Keep paper-only; verify exact-head CI separately.


## 10 November 2026 — pending timestamp cannot delete completed archive evidence

`frontend/tests/hourly-fvg-pending-append.test.ts` now also exercises mirrored bullish and bearish synthetic cases in which a still-open candle's timestamp getter removes an already completed archive row. The scanner must reject the changed archive length rather than silently recalculate a shorter history; future OHLC, volume and minute-coverage getters must remain unread. This tests software snapshot integrity only, not authenticated source provenance, executable broker quotes, fills or profitability. Exact-head CI must be checked after the commit.

## 10 November 2026 — pending timestamp cannot inject archive quote metadata

`frontend/tests/hourly-fvg-pending-archive-metadata.test.ts` adds mirrored synthetic bullish/bearish cases in which a still-open future candle's timestamp accessor inserts a hidden archive-level `askQuoteReceipt` field after the BID-only array schema was first validated. The as-of scanner must reject the changed archive schema, rather than silently drop an undeclared ASK/broker receipt; no future OHLC, volume or minute-coverage getter may run. This checks snapshot schema isolation only: the fixture receipt is not an authenticated two-sided broker quote, volume receipt, execution record or profitability evidence. Exact-head CI must be checked independently.

## 10 November 2026 — hidden broker spread metadata injection

The mirrored bullish/bearish synthetic regression in `frontend/tests/hourly-fvg-pending-archive-metadata.test.ts` now also injects a non-enumerable `brokerSpreadBps` property into the BID-only archive when a still-open future candle's timestamp is inspected. The as-of scanner must reject this out-of-protocol broker-cost metadata rather than silently treating it as authenticated two-sided execution evidence. Future OHLC, volume and minute-coverage getters must remain unread. This does not establish a real broker spread, executable price, fill, or profitable strategy. Verify the exact commit in CI before treating the regression as passed.


## 10 November 2026 — completed close rewrite during pending timestamp access

`frontend/tests/hourly-fvg-pending-completed-close-rewrite.test.ts` adds bullish and bearish synthetic regressions: a still-open successor candle's timestamp getter attempts to change the already-completed formation candle close after the completed prefix was captured. The as-of study must reject the changed completed-candle field and must not inspect the successor's unrevealed OHLC, volume or observed-minute getters. The ordinary unchanged prefix remains a positive control. This checks snapshot consistency only: the source identity and volume remain unverified, and no broker fill, historical return, or trading profitability is demonstrated.

## 10 November 2026 — completed formation wick cannot be rewritten by pending timestamp

The mirrored bullish/bearish synthetic cases in `frontend/tests/hourly-fvg-pending-completed-close-rewrite.test.ts` now also mutate the completed formation candle's low (bullish) or high (bearish) from a still-open successor's timestamp getter. The causal as-of scanner must fail closed on changed completed-candle evidence without evaluating the pending successor's OHLC, volume or observed-minute getters. This complements the completed-close mutation checks; it is not evidence of authentic source archives, two-sided broker fills, or profitability. Confirm exact-head CI independently.


## 10 November 2026 — completed volume and minute-coverage snapshot isolation

`frontend/tests/hourly-fvg-pending-completed-volume-coverage-rewrite.test.ts` adds four mirrored bullish/bearish synthetic checks. Reading only a still-open hour's timestamp attempts to rewrite an already-completed formation candle's reported volume or observed-minute count. The as-of study must reject the completed-row mutation and must not inspect the future candle's OHLC, volume, or minute-coverage accessors. These checks protect snapshot integrity only; synthetic volume is unverified, and neither broker quotes nor strategy profitability are established. Verify the exact PR-head CI separately.

## 10 November 2026 — completed formation open cannot be rewritten by pending timestamp

`frontend/tests/hourly-fvg-pending-completed-open-rewrite.test.ts` adds mirrored bullish/bearish synthetic regressions. A still-open successor's timestamp getter tries to alter the already-completed FVG formation candle's `open` while the causal as-of scan is checking the archive. The scanner must reject the completed-row mutation without inspecting the successor's OHLC, volume or minute-coverage accessors. An unchanged completed prefix is a positive control. These tests establish only internal snapshot consistency, not independently authenticated quotes or volume, executable broker fills, or trading profitability. Keep draft and paper-only; verify exact-head CI separately.

## 10 November 2026 — completed prior-20 baseline close snapshot isolation

`frontend/tests/hourly-fvg-pending-baseline-close-rewrite.test.ts` adds mirrored synthetic bullish/bearish regressions. Reading the timestamp of an unclosed successor hour attempts to rewrite the close of a previously completed candle in the FVG study's prior-20 baseline. The as-of scanner must fail closed rather than accept changed baseline evidence, without reading the future candle's OHLC, volume or observed-minute accessors. This tests internal causal snapshot integrity only; it does not authenticate volume, two-sided broker quotes, fills or profitability. Verify the new exact-head CI before treating the regression as passed.

## 10 November 2026 — prior-20 baseline open snapshot integrity

`frontend/tests/hourly-fvg-pending-baseline-close-rewrite.test.ts` additionally exercises mirrored bullish/bearish synthetic cases where a still-open hour's timestamp accessor rewrites the **open** of an already-completed prior-20 baseline candle. The causal as-of scanner must reject the mutated completed snapshot without accessing the pending hour's OHLC, volume or minute coverage. The previously covered baseline close rewrite remains tested. These checks concern in-memory immutability only: they do not authenticate source-classified volume, broker BID/ASK quotes, financing, calendar evidence, execution or profitability. Keep the PR draft, paper-only and undeployed; verify exact-head CI before review.

## 10 November 2026 — prior-20 wick-extrema snapshot integrity

`frontend/tests/hourly-fvg-pending-baseline-close-rewrite.test.ts` now includes four synthetic bullish/bearish × high/low regressions. Reading a still-open successor's timestamp may not retroactively rewrite the high or low of a completed candle in the prior-20 FVG baseline. The as-of scanner must reject the changed completed snapshot and never read the pending successor's OHLC, volume or minute-coverage fields. These are mutation/causality tests using invented fixture values, **not** authenticated volume, two-sided broker quotes, execution, win-rate or profitability evidence. Keep the PR draft and verify exact-head CI independently.


## 10 November 2026 — completed baseline volume and coverage are immutable

`frontend/tests/hourly-fvg-pending-baseline-volume-coverage-rewrite.test.ts` adds four synthetic bullish/bearish × volume/observed-minute regressions. A still-open successor's timestamp accessor attempts to rewrite a completed candle in the prior-20 FVG baseline; the as-of scan must reject the mutated snapshot while never accessing pending OHLC, volume, or minute coverage. This is source-integrity regression coverage only: the fixture's BID prices and unverified volume cannot establish licensed provenance, broker ASK/spread execution, midpoint fills, or profitable trading. Verify CI on the exact updated PR head before relying on this change.

## 10 November 2026 — completed baseline timestamp integrity

`frontend/tests/hourly-fvg-pending-baseline-time-rewrite.test.ts` adds bullish and bearish synthetic regressions: reading a still-open future candle timestamp attempts to rewrite an already-completed prior-20 baseline candle timestamp. The causal 1H FVG scan must reject the completed-row mutation without accessing the future candle's OHLC, volume, or minute-coverage getters. This is a source-snapshot integrity check only, not authenticated data provenance, real BID/ASK execution, or profitability evidence. Check CI at the exact new head; remain draft, paper-only, unmerged and undeployed.

## 10 November 2026 — exact-head CI repair for baseline timestamp mutation

The two synthetic bullish/bearish pending-timestamp baseline tests initially failed because they expected the generic completed-field snapshot error. The implementation correctly rejects the mutated completed timestamp earlier, at its as-of timestamp declaration-descriptor guard (`FVG as-of timestamp field changed during declaration snapshot`). The regression now asserts that specific early rejection; it continues to require exactly one pending timestamp read and zero future market-field reads. This is a test expectation repair, not a change to production trading behavior or evidence of market-data authenticity, broker fills, or profitability. Verify the **new exact commit** in GitHub Actions before considering CI green; earlier successful runs do not cover this repair.
