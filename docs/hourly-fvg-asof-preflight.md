# Causal 1H FVG as-of cutoff preflight

The research-only as-of scanner validates its caller-supplied UTC hourly close cutoff before reading any source declaration or candle archive. Unsupported cutoffs (including signed zero, nonfinite, fractional, negative, off-hour, and timestamps beyond the documented 2100 horizon) must fail closed. `frontend/tests/hourly-fvg-asof-preflight.test.ts` supplies a hostile synthetic source getter and archive proxy to assert that malformed cutoffs are rejected before any market-data or provenance accessor executes.

This is a narrow software input-ordering regression, not evidence that any price, volume, source identity, broker quote, execution cost, session calendar, or trading result is authentic. Do not merge or deploy the draft on the strength of this test; verify exact-head CI separately.

A second synthetic regression exercises runtime type bypasses (coercible object, numeric-looking string, bigint, null, undefined and boolean). The cutoff must be a primitive number, and hostile coercion hooks must not execute. These tests do not establish authenticated market evidence or strategy returns.

A further synthetic regression covers primitive symbols (local and global registry) and callable objects as invalid cutoffs. The scanner must reject them with the documented validation error before reading archive/source evidence or invoking the supplied callable. This is defensive runtime-type coverage, not a market-data validation or performance result.

A positive-control regression in `frontend/tests/hourly-fvg-valid-asof-boundaries.test.ts` checks that the earliest supported completed hour (3600 UTC seconds) and the inclusive 2100-01-01 UTC horizon pass timestamp preflight and reach archive validation. The hostile synthetic archive deliberately throws at its length getter; this verifies validation ordering, not successful analysis or the authenticity of any historical candles.
