# Causal 1H FVG as-of cutoff preflight

The research-only as-of scanner validates its caller-supplied UTC hourly close cutoff before reading any source declaration or candle archive. Unsupported cutoffs (including signed zero, nonfinite, fractional, negative, off-hour, and timestamps beyond the documented 2100 horizon) must fail closed. `frontend/tests/hourly-fvg-asof-preflight.test.ts` supplies a hostile synthetic source getter and archive proxy to assert that malformed cutoffs are rejected before any market-data or provenance accessor executes.

This is a narrow software input-ordering regression, not evidence that any price, volume, source identity, broker quote, execution cost, session calendar, or trading result is authentic. Do not merge or deploy the draft on the strength of this test; verify exact-head CI separately.

A second synthetic regression exercises runtime type bypasses (coercible object, numeric-looking string, bigint, null, undefined and boolean). The cutoff must be a primitive number, and hostile coercion hooks must not execute. These tests do not establish authenticated market evidence or strategy returns.

A further synthetic regression covers primitive symbols (local and global registry) and callable objects as invalid cutoffs. The scanner must reject them with the documented validation error before reading archive/source evidence or invoking the supplied callable. This is defensive runtime-type coverage, not a market-data validation or performance result.

A positive-control regression in `frontend/tests/hourly-fvg-valid-asof-boundaries.test.ts` checks that the earliest supported completed hour (3600 UTC seconds) and the inclusive 2100-01-01 UTC horizon pass timestamp preflight and reach archive validation. The hostile synthetic archive deliberately throws at its length getter; this verifies validation ordering, not successful analysis or the authenticity of any historical candles.

The positive-control regression also accepts UTC-aligned hourly cutoffs across the 2026 New York spring-forward (2026-03-08 07:00 UTC) and fall-back (2026-11-01 06:00 UTC) transitions. These are UTC timestamp validation checks only: they do not assert any broker session, exchange calendar, financing cutoff or universal 17:00 New York close.

The DST positive control now checks the immediately preceding and following UTC hours as well as the transition hour for both March and November 2026 (six cutoffs total). Each must reach archive validation exactly once. This guards against accidentally treating a skipped or repeated *local* New York hour as an invalid UTC cutoff; it does not verify exchange opening hours or broker rollover schedules.
