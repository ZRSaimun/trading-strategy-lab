# Pending-hour signed-zero timestamp isolation (synthetic regression)

The standalone causal 1H FVG as-of scanner must preserve the exact value of every completed candle timestamp during the scan of still-open future timestamps. JavaScript compares `0 === -0` as true, but `Object.is(0,-0)` as false. The completed-snapshot comparison now uses `Object.is` to reject a future timestamp getter that changes the already-observed first hourly timestamp from positive zero to negative zero.

`frontend/tests/hourly-fvg-pending-signed-zero-time-revision.test.ts` exercises both bullish and bearish synthetic formations. Each test first confirms that an unchanged completed prefix can be studied, then appends a pending hour whose time getter rewrites the completed timestamp. The scanner must throw the earlier declaration-snapshot timestamp integrity error after exactly one pending timestamp read without invoking future OHLC, volume, or minute-coverage getters.

This protects representation-level causality; it does **not** independently authenticate the historical archive, volume-source identity, BID/ASK broker quotes, fill feasibility, costs, news evidence, or trading profitability. All tests are paper-only and synthetic; no orders or deployment are authorized.

A paired positive control for each direction appends a benign pending timestamp getter with forbidden future market-field getters. The completed-prefix observations must remain identical to those without the pending candle, with exactly one timestamp read and zero future market-field reads. This prevents the integrity guard from becoming an unconditional rejection of valid timestamp-only pending data.

A recovery regression also verifies that, after the scanner rejects a pending getter's signed-zero mutation, explicitly restoring the completed timestamp and removing the hostile pending row reproduces the original completed-prefix observations. This checks deterministic re-evaluation after caller-side correction, not automatic repair or source authenticity.

## 12 November 2026 — CI TypeScript repair

The recovery regression's intentionally forbidden future OHLC/volume getters return `never` (inferred as `void` in the object literal), so a direct `as Bar` assertion failed TypeScript's TS2352 structural-overlap check during Next.js production builds. The test now uses `as unknown as Bar`, matching the other deliberately hostile pending-row fixtures. This is confined to a synthetic test: the runtime scanner still must not read those getters. Frontend, Docker smoke and free-cloud smoke builds previously failed on the same type-check error; the updated commit requires fresh exact-head CI verification before claiming a pass.

## Reverse signed-zero mutation regression

`frontend/tests/hourly-fvg-pending-reverse-signed-zero-time.test.ts` covers a distinct **preflight ordering** boundary. The completed archive already contains a prohibited `-0` timestamp, so the scanner must reject it before invoking a pending hour's timestamp getter that would attempt to rewrite it to `+0`. Both bullish and bearish synthetic fixtures require **zero pending timestamp reads**, zero future OHLC/volume/coverage reads, and preservation of the invalid completed timestamp. The initial version of this test incorrectly expected a successful baseline and a later mutation error; exact-head frontend CI caught that error (2 failed tests of 1,251). The corrected regression checks the actual fail-closed contract. This is representation-integrity evidence only; source authentication, real BID/ASK quotes, execution feasibility and profitability remain unverified.

## Pending timestamp archive-row substitution

`frontend/tests/hourly-fvg-pending-row-swap.test.ts` adds mirrored bullish/bearish synthetic checks for a separate as-of provenance boundary: a future, unclosed hour's timestamp getter must not replace an already-completed candle object with a distinct object containing identical field values. The archive-slot identity guard must reject the swap after one timestamp read, without reading future OHLC, volume or minute-coverage fields. Matching price numbers alone are not sufficient evidence of an unchanged historical archive. This does not authenticate the input source or establish a broker fill, strategy edge or profitability.

## Latest completed formation-row substitution regression

The pending-row-swap test now also checks the **last completed hourly formation candle** (index 22), in both bullish and bearish synthetic fixtures. A pending hour's timestamp accessor replaces that completed object with a new object containing identical fields. The as-of study must reject the archive identity change after exactly one pending timestamp read, without accessing future OHLC, volume or minute coverage. This complements the first-row substitution test; it does not prove independent source provenance, market performance or execution feasibility. Exact-head CI must be checked for the new commit.

## Prior-20 baseline row identity (12 November 2026)

Synthetic bullish and bearish regressions now check a pending hourly timestamp accessor attempting to substitute a middle completed candle used in the historical volume-baseline window with a distinct object carrying identical values. The as-of scanner must fail closed after one pending timestamp read and before any future OHLC, volume, or minute-coverage access. This checks in-memory archive consistency, not independent volume-source authentication, real BID/ASK quotes, executable fills, or trading returns. Exact-head CI must be checked after the commit.

## Completed-row permutation regression (12 November 2026)

Mirrored bullish/bearish synthetic tests now exercise a pending timestamp accessor that swaps two already-completed historical row objects without changing archive length, row values, or the multiset of object identities. The as-of scanner must reject the changed slot-to-object mapping after exactly one pending timestamp read, before any future OHLC, volume, or minute-coverage access. This tests causal archive chronology rather than market-source authenticity; it provides no broker execution or profitability evidence. Exact-head CI verification is required for the new commit.

## Completed archive-slot descriptor regression (12 November 2026)

The pending-row-swap suite now also tests a future timestamp accessor changing a completed volume-baseline slot from writable to read-only without changing the candle object or its values. Mirrored bullish/bearish synthetic tests require fail-closed archive-slot identity validation after exactly one pending timestamp read and zero future market-field reads. This verifies that a same-value property-descriptor mutation cannot silently pass as an unchanged historical snapshot. It does not authenticate data, prove fills or profitability. Verify the exact-head GitHub Actions workflow before considering the regression accepted.

## Pending timestamp hides completed indexed slot (12 November 2026)

Mirrored synthetic bullish/bearish regressions verify that a still-open future hour's timestamp getter cannot make a completed, previously enumerable archive index non-enumerable while preserving the exact same candle object and values. The as-of scan must reject the archive-slot descriptor change after one pending timestamp read, without accessing future OHLC, volume or minute coverage. This is a representation-level causality guard, not independently authenticated source volume, real BID/ASK quotes or profitability evidence. Exact-head CI remains required.

## Pending timestamp truncates completed archive (12 November 2026)

`frontend/tests/hourly-fvg-pending-truncation.test.ts` adds mirrored synthetic bullish/bearish checks that an unclosed hour's timestamp accessor cannot shorten the previously observed completed candle array. The causal scanner must reject the changed historical snapshot after one pending timestamp read without reading future OHLC, volume or minute-coverage fields. This protects in-memory causal consistency only; it does not authenticate source data, model fills or demonstrate profitability. Exact-head CI must verify the regression.

## Pending timestamp prepend regression (12 November 2026)

Synthetic bullish/bearish tests in `frontend/tests/hourly-fvg-pending-prepend.test.ts` assert that a still-open candle's timestamp getter cannot prepend a historical row to the already-observed hourly archive. The as-of scan must reject the archive-length mutation after one timestamp read and before any pending OHLC, volume or minute-coverage access. This is snapshot integrity only; it does not validate source identities, CFD quotes, execution costs or profitability.

## Completed baseline slot deletion during pending timestamp access

The synthetic `hourly-fvg-pending-delete-slot.test.ts` regression covers a future candle timestamp getter deleting an already-completed prior-20 volume-baseline array index while preserving the array length. A sparse hole is not an observed closed candle and must fail the as-of snapshot before any future OHLC, volume, or minute-coverage access. Both bullish and bearish formation fixtures are checked. This is a representation-integrity test only: it does not authenticate volume, prices, broker costs, or profitability.

## Sparse-slot rejection recovery regression

`frontend/tests/hourly-fvg-pending-delete-slot.test.ts` now also verifies both formation directions recover the exact completed-prefix study output after the caller removes the hostile pending row and restores the deleted prior-20 volume-baseline candle. Rejection is fail-closed for the corrupted invocation, but must not contaminate a subsequent clean, independently evaluated scan. The fixture is synthetic and supplies no independently authenticated volume, executable quote, or trading edge.

## Truncated archive recovery after caller restoration (12 November 2026)

`frontend/tests/hourly-fvg-pending-truncation.test.ts` now also verifies both bullish and bearish synthetic cases can be re-evaluated deterministically after a rejected pending timestamp getter truncates the completed archive. The caller explicitly reconstructs the original completed rows from an independent copy, removes the hostile pending row, and requires the next as-of result to match the clean completed-prefix study. This does **not** imply the scanner repairs a damaged input archive automatically. The test establishes local fail-closed/recovery behavior only; source provenance, volume authenticity, broker BID/ASK execution, costs, and profitability remain unverified. Exact-head CI is required for the updated regression.

## Prepend archive recovery after caller restoration (12 November 2026)

`frontend/tests/hourly-fvg-pending-prepend.test.ts` now verifies both bullish and bearish synthetic studies can be reproduced after a pending timestamp getter prepends a row and the scanner rejects the changed archive length. The caller explicitly removes the hostile pending row and reconstructs the original completed prefix from a separate copy; the subsequent as-of result must equal the independently computed clean baseline. This tests deterministic recovery after caller repair, not automatic data repair, authenticated market provenance, executable quotes, or profitability. The new commit requires exact-head CI verification.

## Pending append/removal recovery after caller restoration (12 November 2026)

`frontend/tests/hourly-fvg-pending-append.test.ts` now checks deterministic re-evaluation for both bullish and bearish synthetic formations after a pending timestamp getter either appends an unseen hour or removes a completed archive row. Each rejected scan must avoid future OHLC, volume and minute-coverage reads; the caller then explicitly reconstructs the original completed archive from a separate copy, and the next scan must match the clean baseline exactly. This is not automatic repair, authenticated volume provenance, real BID/ASK execution, or evidence of profitability. Verify the updated PR head in CI.
