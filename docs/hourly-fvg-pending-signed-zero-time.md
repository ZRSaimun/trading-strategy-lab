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
