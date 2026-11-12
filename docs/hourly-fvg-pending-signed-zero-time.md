# Pending-hour signed-zero timestamp isolation (synthetic regression)

The standalone causal 1H FVG as-of scanner must preserve the exact value of every completed candle timestamp during the scan of still-open future timestamps. JavaScript compares `0 === -0` as true, but `Object.is(0,-0)` as false. The completed-snapshot comparison now uses `Object.is` to reject a future timestamp getter that changes the already-observed first hourly timestamp from positive zero to negative zero.

`frontend/tests/hourly-fvg-pending-signed-zero-time-revision.test.ts` exercises both bullish and bearish synthetic formations. Each test first confirms that an unchanged completed prefix can be studied, then appends a pending hour whose time getter rewrites the completed timestamp. The scanner must throw the earlier declaration-snapshot timestamp integrity error after exactly one pending timestamp read without invoking future OHLC, volume, or minute-coverage getters.

This protects representation-level causality; it does **not** independently authenticate the historical archive, volume-source identity, BID/ASK broker quotes, fill feasibility, costs, news evidence, or trading profitability. All tests are paper-only and synthetic; no orders or deployment are authorized.

A paired positive control for each direction appends a benign pending timestamp getter with forbidden future market-field getters. The completed-prefix observations must remain identical to those without the pending candle, with exactly one timestamp read and zero future market-field reads. This prevents the integrity guard from becoming an unconditional rejection of valid timestamp-only pending data.

A recovery regression also verifies that, after the scanner rejects a pending getter's signed-zero mutation, explicitly restoring the completed timestamp and removing the hostile pending row reproduces the original completed-prefix observations. This checks deterministic re-evaluation after caller-side correction, not automatic repair or source authenticity.

## 12 November 2026 — CI TypeScript repair

The recovery regression's intentionally forbidden future OHLC/volume getters return `never` (inferred as `void` in the object literal), so a direct `as Bar` assertion failed TypeScript's TS2352 structural-overlap check during Next.js production builds. The test now uses `as unknown as Bar`, matching the other deliberately hostile pending-row fixtures. This is confined to a synthetic test: the runtime scanner still must not read those getters. Frontend, Docker smoke and free-cloud smoke builds previously failed on the same type-check error; the updated commit requires fresh exact-head CI verification before claiming a pass.

## Reverse signed-zero mutation regression

`frontend/tests/hourly-fvg-pending-reverse-signed-zero-time.test.ts` independently checks the opposite completed timestamp representation change, from `-0` to `+0`, in both bullish and bearish synthetic FVGs. A still-open pending hour may expose its timestamp once, but cannot rewrite the earlier completed timestamp, and no future OHLC, volume or coverage accessor may be evaluated. This is a representation-integrity test only; source authentication, real BID/ASK quotes, execution feasibility and profitability remain unverified.
