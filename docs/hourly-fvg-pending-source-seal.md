# Pending-hour source declaration seal regression

The causal 1H FVG as-of study must reject a pending (not yet closed) hourly candle whose timestamp accessor irreversibly changes the property descriptor of an already-declared source identity field. This includes dataset ID, archive SHA-256, instrument, provider, BID side, declared volume type, and the volume-verification flag. Even if the value is unchanged, the source declaration's representation changed *after* the completed prefix was read.

`frontend/tests/hourly-fvg-pending-source-seal.test.ts` supplies fifty-six synthetic mutation cases plus two non-mutating controls and two additional fail-closed future-hour regressions (seven fields × four descriptor variants, seven deletion cases, and seven value-rewrite cases). Two variants permanently make one source field non-configurable, either retaining writability or also making it non-writable. A third variant retains configurability but removes writability during exactly one future timestamp read. A fourth variant makes the field non-enumerable while leaving it configurable and writable, hiding the declared identity from ordinary serialization. All four alter the snapshotted declaration without changing its value. Seven additional cases delete an own source field during the pending-hour timestamp read, without substituting an inherited value. These must fail closed as well, before any future market field is accessed. The scan must fail closed without reading any future OHLC, volume, or minute-coverage field. An irreversible mutation cannot be undone in place; callers must reconstruct the declaration from independent evidence before retrying. Even a technically reversible descriptor change must not be silently accepted as unchanged provenance.

Seven prototype-substitution cases remove an own source field and supply an inherited field of the same value during the pending timestamp read. Even matching inherited values are not an authenticated own declaration; the scan must reject them before future OHLC, volume or coverage reads.

Seven further cases rewrite an already-snapshotted source value during the pending timestamp getter, including a changed dataset hash, provider, declared price side, and volume-verification status. These must reject the stale snapshot before reading any pending market values, even where the replacement value is otherwise well-formed. The intentionally invalid ASK declaration is never accepted as a valid BID source.

These tests establish only in-memory declaration consistency. They do not verify a volume provider, license, raw source receipt, BID/ASK quote, execution cost, fill, trading outcome, or profitability. Keep the study draft, paper-only, unmerged and undeployed pending exact-head CI and independent evidence.

## Pending-hour data-to-accessor source substitution

Seven additional synthetic regressions cover replacing each previously snapshotted own source-identity data field with an enumerable accessor returning the same value. The as-of scan must reject the descriptor-type mutation after exactly one pending timestamp read, without invoking the replacement source getter or any future OHLC, volume or minute-coverage getter. Matching returned values cannot authenticate a changed evidence declaration. This is an integrity regression, not verification of real source receipts, broker execution or profitability.

## Valid pending-hour and strictly future-hour controls

A non-mutating pending timestamp accessor is accepted as an ordinary as-of boundary. The synthetic control asserts that the pending timestamp is read once and pending OHLC, volume and observed-minute accessors are never invoked. This prevents the mutation rejection tests from passing merely because the scanner rejects every pending timestamp. This control is not a real-data or profitable-strategy validation.

A second non-mutating synthetic control places the last hourly timestamp strictly after the as-of cutoff. It verifies the scanner reads that timestamp once, skips the future bar, and never invokes its OHLC, volume, or minute-coverage accessors. This is a causal boundary check, not source authentication or trading-performance evidence.

## Strictly future timestamp side-effect guard

A synthetic regression now changes the completed-prefix dataset identity while reading a timestamp strictly later than the as-of cutoff. Even though the future candle itself is skipped, the scanner must reject the changed source declaration after one timestamp read and without reading future OHLC, volume, or coverage. This closes the gap between the non-mutating future-hour control and pending-hour source-mutation cases. It does not validate real source identity or strategy profitability.

## Unavailable future timestamp control

A synthetic future hourly timestamp getter that throws must terminate the causal scan without accessing any future OHLC, volume, or observed-minute getter. The test checks one timestamp read and zero future market-field reads. This verifies fail-closed propagation for an inaccessible timestamp, not provider authenticity, market performance, or profitability.

## Non-finite future timestamp control

A synthetic future-hour timestamp accessor returning `NaN` must cause the as-of scanner to reject the archive after exactly one timestamp read, without accessing the future candle's OHLC, volume, or minute-coverage getters. This complements the throwing-accessor control: an invalid numeric timestamp is not a closed bar and cannot be interpreted as evidence of a trade. These checks do not establish source authenticity or profitability.

## Infinite future timestamps

Two additional synthetic regressions reject positive and negative infinity in the final hourly timestamp getter. Each checks that the causal as-of scan reads that timestamp exactly once and never touches its future OHLC, volume or observed-minute fields. Together with the NaN control, these distinguish malformed numeric evidence from an ordinary strictly future bar. These checks do not authenticate a source or establish profitability.

## Non-numeric pending timestamp boundary

Two synthetic cases supply a pending-hour timestamp as `null` or a numeric-looking string. Neither is a valid numeric closed-bar receipt; implicit JavaScript coercion must not turn them into admissible evidence. Each case asserts one timestamp read, rejection, and zero reads of pending OHLC, volume, or observed-minute fields. This tests input validation only and does not authenticate market data, source volume, broker quotes, fills, or profitability.

## Boolean and missing pending-hour timestamps

Three synthetic cases reject `false`, `true`, and `undefined` pending-hour timestamps. In JavaScript, booleans can coerce to numeric zero or one, and a missing timestamp is not a completed-bar receipt. Each regression asserts one timestamp access and no future OHLC, volume, or coverage reads. These are parser/causality checks only; no real quote or profitability evidence is claimed.

## Non-JSON timestamp types

Two synthetic as-of regressions reject a pending hourly timestamp represented as a JavaScript `bigint` or `symbol`. Neither is a valid JSON numeric UTC close timestamp; the scanner must not coerce either into closed-bar evidence. Both tests require exactly one timestamp read and no access to pending OHLC, volume, or observed-minute fields. These tests are input-integrity checks, not source authentication, trading execution or profitability evidence.

## Object timestamp coercion boundary

A synthetic regression supplies an object-valued pending-hour timestamp with hostile `valueOf` and `toString` hooks. The causal as-of scanner must reject the non-numeric timestamp after one timestamp read without invoking either coercion hook or reading any pending OHLC, volume, or minute-coverage field. This prevents a malformed timestamp object from executing side effects during implicit numeric comparison. It does not validate market provenance or profitability.

## Off-grid future-hour timestamps

A synthetic regression supplies a strictly future timestamp one millisecond beyond a UTC hour boundary. The causal 1H FVG scanner must reject the off-grid value rather than simply ignoring it as future data, and must not read the corresponding future OHLC, volume or minute-coverage fields. This checks archive timestamp alignment, not the authenticity of the originating feed or profitability. Exact-head CI must be verified before treating this change as regression-protected.

## Future timestamp cost-array iterator injection

A future hourly timestamp getter must not add an own `Symbol.iterator` property to an already snapshotted hypothetical cost-scenario array. The as-of cost schema now rejects this undeclared symbol key instead of exempting it. `frontend/tests/hourly-fvg-future-cost-iterator.test.ts` checks that the mutation fails closed after one future timestamp read, without invoking the injected iterator getter or reading future OHLC, volume or coverage. An ordinary unchanged numeric cost array remains accepted as a positive control.

This prevents in-memory study-configuration drift only. It does not validate the illustrative bps costs against actual two-sided broker demo quotes, establish licensed market-data provenance, or prove profitable trading. The PR remains draft and paper-only.


## CI regression repair — own cost-array iterator

The strict cost-array `Symbol.iterator` rejection introduced on this draft branch invalidated an older v49 test that still expected a custom own iterator to be accepted. The regression now requires both full-history and causal as-of paths to reject that unsupported array metadata; it also retains a normal numeric-cost control. This is a test expectation repair following the fail-closed schema change, not a relaxation of the source gate. GitHub Actions must pass on the new exact head before claiming verification. No real broker quotes, authenticated volume or trading-profit evidence is implied.

## 14 November 2026 — exact-head frontend CI repair

Workflow [#43585073224](https://github.com/ZRSaimun/trading-strategy-lab/actions/runs/43585073224) failed one of 1,385 frontend tests: the v49 regression correctly expected rejection of an own cost-array `Symbol.iterator`, but the full-history configuration preflight still exempted that key in two passes. Both exemptions are removed, aligning the full-history and causal as-of schema with the intended fail-closed policy. The regression additionally checks that an iterator accessor is never executed on either path; ordinary numeric arrays remain supported. The five other CI jobs on the failing run passed. Verify new exact-head CI separately; neither a prior pass nor this patch proves the new head passes. This is synthetic input integrity, not independently sourced broker quotes, volume or profitability evidence.

## 14 November 2026 — normal-cost control CI repair

Exact-head [workflow #43590191994](https://github.com/ZRSaimun/trading-strategy-lab/actions/runs/43590191994) failed one frontend test (1,384/1,385 passed), while five other jobs passed. The iterator-rejection regression correctly expected both FVG entry points to reject custom candle/cost iterators, but its final positive control reused the same invalid cost array. The positive control now supplies a fresh ordinary `[0,5,15]` array; the hostile iterator rejection assertions remain unchanged. This is a regression fixture correction, not evidence of broker cost accuracy, execution or profitability. Verify CI on the new exact head before claiming a pass; keep draft, paper-only and undeployed.

## Exact as-of cutoff boundary regression (14 November 2026)

A synthetic hourly candle whose UTC **start** equals the as-of cutoff is pending, not a completed candle. The causal 1H FVG study must match the report from the completed prefix, read the pending timestamp only once, and never read that pending candle's OHLC, volume or observed-minute fields. Regression: `frontend/tests/hourly-fvg-pending-source-seal.test.ts`. This validates a narrow no-lookahead boundary, not source authentication, executable broker quotes or profitable performance. No orders, merge or deployment.

## UTC hourly causal boundary during New York fall-back (14 November 2026)

A synthetic regression places the as-of cutoff at `2026-11-01T06:00:00Z`, the New York autumn clock-change instant. The candle starting exactly at that UTC cutoff remains pending; the report must equal the completed-prefix result, read the pending timestamp once and never read its OHLC, volume or observed-minute fields. This prevents accidental use of a New York local-hour assumption in the hourly research boundary. It does **not** establish broker-specific financing cutoffs, actual session calendars, volume provenance, execution quotes or profitability. The PR remains draft, paper-only, unmerged and undeployed; verify exact-head CI separately.

## UTC spring-forward causal boundary (14 November 2026)

A companion synthetic regression places the as-of cutoff at `2026-03-08T07:00:00Z`, when New York advances its clocks. An hourly candle beginning at that UTC cutoff remains pending, and the causal study must match the completed-prefix report while reading its timestamp once and none of its OHLC, volume, or minute-coverage fields. This complements the autumn fall-back test and prevents treating the skipped local wall-clock hour as completed market evidence. The study uses UTC hour boundaries; it does not establish actual exchange calendars, broker-specific financing times, authorized quote sources, or profitability. Keep this work draft, paper-only and undeployed; confirm CI on the exact updated head.

## 14 November 2026 — DST fixture unit correction

Corrected the two New York DST boundary regression fixtures to convert JavaScript `Date.UTC(...)` **milliseconds** to the FVG engine's UTC **epoch seconds** (`/1000`). The fall-back fixture now uses the actual `2026-11-01T06:00:00Z` epoch-second instant with 3,600-second adjacent hourly bars, and the spring-forward fixture uses `2026-03-08T07:00:00Z` with the same units. Each asserts its round-tripped ISO UTC instant before checking the pending-candle no-lookahead boundary. Previously the tests used millisecond epochs with 3,600-second spacing, so their descriptions did not correspond to actual 2026 clock-change instants in the engine. These remain synthetic causal-timing checks, not exchange-session calendar, broker financing-cutoff, licensed feed or profitability verification. Confirm CI for the exact new PR head separately.


## 14 November 2026 — millisecond as-of cutoff rejection

The causal 1H FVG as-of entry point now rejects UTC cutoffs later than 2100-01-01T00:00:00Z (epoch seconds). This explicit research horizon prevents a JavaScript `Date.UTC(...)` **millisecond** timestamp for modern dates from being silently accepted as a far-future, hour-aligned seconds timestamp. Synthetic regressions cover the 2026 New York spring and autumn clock-change instants supplied incorrectly in milliseconds, asserting rejection before reading even a candle timestamp or market field. Valid epoch-second cutoffs at those instants remain covered by the existing DST regressions. The year-2100 ceiling is a declared software validation horizon, **not** a verified trading-session calendar or broker financing schedule; data beyond it require a deliberate versioned rule change. No live prices, authenticated volume, real quotes, or profitability are implied. Keep draft, paper-only and undeployed; exact-head CI must be checked separately.

## Future archive timestamp horizon (14 November 2026)

The causal 1H FVG as-of scanner now rejects even a **future-only** archive timestamp later than `2100-01-01T00:00:00Z`, consistent with the existing upper bound on the as-of cutoff. Previously, an otherwise aligned, safe-integer future timestamp could be silently skipped without the same unit/horizon check. A synthetic regression requires fail-closed rejection after one future timestamp read and zero future OHLC, volume or minute-coverage reads; a normally aligned future timestamp remains skippable. This is a conservative input-integrity horizon, not a verified market calendar or broker financing schedule. No real volume-source, executable quote, profitability or live-order evidence is claimed. Verify exact-head CI before considering the change tested.

## Multiple pending future-hour bars (14 November 2026)

A synthetic regression now supplies two strictly future, UTC-aligned hourly bars after a completed prefix. Their timestamps are allowed to be read once each for chronological validation, but all OHLC, volume and observed-minute getters throw if touched. The causal report must exactly match the completed-prefix report. This protects the timestamp-only rule across more than one pending bar rather than only the first boundary bar. It is not a real-feed acceptance test, volume provenance, broker quote validation or evidence of profitability. Keep this draft paper-only; verify exact-head CI after the change.

## Second future-hour source drift (14 November 2026)

A synthetic two-future-bar regression checks that a benign first future timestamp does not disable provenance checks for a later future timestamp. The second timestamp getter rewrites the already-declared archive SHA-256. The causal 1H FVG study must reject that source-identity drift after one read of each future timestamp, without accessing either future candle's OHLC, volume or observed-minute fields. This is a regression for repeated as-of snapshot checks, not a verified provider receipt, broker quote, executable strategy, or profitability result. Keep the PR draft, paper-only and unmerged; verify CI on the exact updated head.
