# Causal 1H FVG as-of cutoff preflight

The research-only as-of scanner validates its caller-supplied UTC hourly close cutoff before reading any source declaration or candle archive. Unsupported cutoffs (including signed zero, nonfinite, fractional, negative, off-hour, and timestamps beyond the documented 2100 horizon) must fail closed. `frontend/tests/hourly-fvg-asof-preflight.test.ts` supplies a hostile synthetic source getter and archive proxy to assert that malformed cutoffs are rejected before any market-data or provenance accessor executes.

This is a narrow software input-ordering regression, not evidence that any price, volume, source identity, broker quote, execution cost, session calendar, or trading result is authentic. Do not merge or deploy the draft on the strength of this test; verify exact-head CI separately.

A second synthetic regression exercises runtime type bypasses (coercible object, numeric-looking string, bigint, null, undefined and boolean). The cutoff must be a primitive number, and hostile coercion hooks must not execute. These tests do not establish authenticated market evidence or strategy returns.

A further synthetic regression covers primitive symbols (local and global registry) and callable objects as invalid cutoffs. The scanner must reject them with the documented validation error before reading archive/source evidence or invoking the supplied callable. This is defensive runtime-type coverage, not a market-data validation or performance result.

A positive-control regression in `frontend/tests/hourly-fvg-valid-asof-boundaries.test.ts` checks that the earliest supported completed hour (3600 UTC seconds) and the inclusive 2100-01-01 UTC horizon pass timestamp preflight and reach archive validation. The hostile synthetic archive deliberately throws at its length getter; this verifies validation ordering, not successful analysis or the authenticity of any historical candles.

The positive-control regression also accepts UTC-aligned hourly cutoffs across the 2026 New York spring-forward (2026-03-08 07:00 UTC) and fall-back (2026-11-01 06:00 UTC) transitions. These are UTC timestamp validation checks only: they do not assert any broker session, exchange calendar, financing cutoff or universal 17:00 New York close.

The DST positive control now checks the immediately preceding and following UTC hours as well as the transition hour for both March and November 2026 (six cutoffs total). Each must reach archive validation exactly once. This guards against accidentally treating a skipped or repeated *local* New York hour as an invalid UTC cutoff; it does not verify exchange opening hours or broker rollover schedules.

The same positive-control suite also checks UTC hourly closes at 2038-01-19 03:00 and 04:00 UTC, straddling the signed 32-bit Unix timestamp rollover (03:14:08 UTC). Both must pass cutoff preflight and reach archive validation. This detects accidental 32-bit timestamp truncation in the cutoff path, but does not establish compatibility of upstream feeds, storage, broker calendars, or historical datasets with 2038 dates.

The UTC calendar positive control also checks 2028-02-28 23:00, 2028-02-29 00:00 and 23:00, and 2028-03-01 00:00. All four must pass hourly cutoff preflight and reach archive validation, including the leap-day boundary. This does not verify actual market sessions or feed coverage on those dates.

The inclusive-horizon positive control also covers 2099-12-31 23:00 UTC, the last completed hourly cutoff before 2100-01-01 00:00 UTC. Both reach archive validation, guarding against an off-by-one rejection at the supported upper boundary. It does not validate real market-data coverage at either timestamp.

A further synthetic regression uses a proxy source with hostile property reads, key enumeration, and property-descriptor traps. Invalid as-of cutoffs must be rejected before **any** source provenance introspection, not merely before a named field getter. This checks validation ordering only; it cannot authenticate source declarations or historical market data.

The invalid-cutoff regression also installs hostile prototype-discovery, membership, mutation and property-definition proxy traps on both source and archive. None may run before the cutoff validation error. This guards the no-evidence-access ordering contract; it does not validate market prices, volume provenance or trading outcomes.

The revoked-proxy regression additionally proves that malformed cutoffs are rejected before any operation on revoked source/archive proxies (which would otherwise throw a native proxy error). This is a synthetic input-precedence check, not an authentication or market-quality check.

A null-evidence positive-precedence regression passes invalid UTC cutoffs alongside absent source and archive objects (runtime TypeScript bypass). The timestamp error must win before source/archive type checks. This does not make missing evidence acceptable for a valid cutoff or demonstrate market-data quality.

A valid UTC hourly cutoff (3600 seconds) paired with a null, undefined, or non-array candle archive must fail closed with the archive-validation error before inspecting source provenance. The synthetic regression prevents missing evidence from being misrepresented as an evaluated empty study. It does not authenticate any volume or price feed, prove strategy returns, or permit live orders.

A runtime-type regression also supplies primitive candle archives (boolean, number, string, bigint and symbol) alongside a valid UTC hourly cutoff and a hostile source proxy. Each must fail archive validation before provenance inspection; no primitive can be treated as an empty or successfully evaluated dataset. These synthetic cases do not establish real-source integrity, broker execution, or profitability.
