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
