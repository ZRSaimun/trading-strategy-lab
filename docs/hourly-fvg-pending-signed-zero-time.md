# Pending-hour signed-zero timestamp isolation (synthetic regression)

The standalone causal 1H FVG as-of scanner must preserve the exact value of every completed candle timestamp during the scan of still-open future timestamps. JavaScript compares `0 === -0` as true, but `Object.is(0,-0)` as false. The completed-snapshot comparison now uses `Object.is` to reject a future timestamp getter that changes the already-observed first hourly timestamp from positive zero to negative zero.

`frontend/tests/hourly-fvg-pending-signed-zero-time-revision.test.ts` exercises both bullish and bearish synthetic formations. Each test first confirms that an unchanged completed prefix can be studied, then appends a pending hour whose time getter rewrites the completed timestamp. The scanner must throw the earlier declaration-snapshot timestamp integrity error after exactly one pending timestamp read without invoking future OHLC, volume, or minute-coverage getters.

This protects representation-level causality; it does **not** independently authenticate the historical archive, volume-source identity, BID/ASK broker quotes, fill feasibility, costs, news evidence, or trading profitability. All tests are paper-only and synthetic; no orders or deployment are authorized.

A paired positive control for each direction appends a benign pending timestamp getter with forbidden future market-field getters. The completed-prefix observations must remain identical to those without the pending candle, with exactly one timestamp read and zero future market-field reads. This prevents the integrity guard from becoming an unconditional rejection of valid timestamp-only pending data.
