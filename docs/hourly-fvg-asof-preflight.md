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

A synthetic array-like impostor with hostile `length` and indexed candle getters must also be rejected at a valid cutoff before those getters or source metadata run. This closes a runtime archive-shape spoofing case; only actual arrays can proceed to evidence checks. It is not a market-data provenance receipt or a trading-performance result.

An oversized 20,001-slot hourly archive is rejected at a valid as-of cutoff before reading indexed candles, enumerating the archive, or inspecting source declarations. The synthetic proxy permits only its array length to be read; this tests the 20,000-row work bound and evidence-access ordering, not whether any dataset is genuine or any strategy is profitable.

A separate synthetic accessor-slot regression supplies an actual one-row array whose own index `0` is a getter. With a valid completed-hour cutoff, the as-of scanner must reject this unstable archive slot before invoking the getter or inspecting source metadata. An accessor-backed row could otherwise return different candles across reads; the test verifies defensive ordering only, not real-feed provenance or profitability.

The maximum 20,000-slot archive length is inclusive, but a sparse array of exactly that length still fails the own-index candle-evidence check before source provenance inspection. This synthetic boundary regression separates the work-limit policy from the requirement for actual immutable historical rows; it does not establish feed authenticity, source licensing, broker fills or profitability.

A prototype-inherited candle slot is not owned historical archive evidence, even if JavaScript indexed access would find it. A synthetic regression uses an inherited throwing getter to verify that the scanner rejects the hole without evaluating that getter or inspecting source metadata. This protects the causal evidence boundary, not any market outcome.

A non-enumerable own indexed candle slot is also hidden evidence, even when it holds a row object. The synthetic regression confirms the as-of scanner rejects such a slot before reading its candle fields or source declaration. This checks archive completeness and validation order only; it cannot establish source authenticity or a trading edge.

A valid completed-hour cutoff also rejects an undeclared archive-level `askQuotes` getter before invoking that getter or inspecting source provenance. The synthetic case demonstrates that an extra ASK-side payload cannot silently accompany the frozen BID-only candle array; it does **not** authenticate a real two-sided broker quote or establish realistic execution costs.

A valid completed-hour cutoff also rejects an own `Symbol.iterator` override on the BID-only archive before executing its getter or inspecting source metadata. The synthetic regression ensures a caller-controlled iterator cannot be silently admitted as undeclared archive behavior; it does not prove price or volume authenticity, execution quality, or profitability.

A further synthetic regression rejects a non-enumerable symbol-keyed archive receipt (for example, an undeclared ASK-side payload) before executing its getter or reading source identity. This ensures that symbol metadata cannot bypass the BID-only array schema; it does not validate broker ASK quotes or volume provenance.

A synthetic regression also rejects a numeric-looking own archive property at `4294967295` (2^32−1), which JavaScript does not count as an array index. The as-of scanner must reject that undeclared metadata without executing its getter or reading source identity. This prevents an unaccounted extra candle or quote payload from being silently accepted; it does not authenticate market data or prove a trading edge.

A further synthetic regression rejects noncanonical numeric-looking archive properties (`-1`, `01`, and `1.0`) without executing hidden payload getters or inspecting source provenance. These are not JavaScript array indices, so accepting them would silently retain unaudited data outside the frozen BID-only archive. The test is a schema-boundary check, not authenticated quote, volume, fill, or profitability evidence.

An additional synthetic regression supplies hostile archive, source and cost-configuration proxies together with invalid completed-hour cutoffs. The timestamp preflight must reject them without triggering any property, key or descriptor inspection, including cost-scenario declarations. This is a validation-order guarantee only; no authentic broker spread, source-classified volume, trade execution or profitability is inferred.

A valid completed-hour cutoff with a missing/non-array hourly archive must fail the archive evidence preflight **before** optional cost-scenario objects or source metadata are inspected. The synthetic regression supplies hostile cost and source proxies alongside null, undefined and object impostor archives. This prevents malformed optional cost inputs from obscuring absent candle evidence. It does not establish genuine market provenance, broker execution costs or trading profitability.

An oversized 20,001-slot hourly archive must also be rejected **before** evaluating optional cost-scenario configuration or source provenance. A synthetic hostile-proxy regression permits only the array length read and asserts that no row, cost or source getter is invoked. This is bounded-work and validation-precedence evidence, not a broker quote, source receipt, market-data acceptance test or profitability finding.

A valid completed-hour cutoff with an accessor-backed indexed candle must fail the own-data-property archive gate **before** inspecting optional cost scenarios or source provenance. A synthetic hostile-getter regression checks that neither the candle accessor nor cost/source traps execute. This validates input precedence, not authentic market data, execution prices, or profitability.

A synthetic precedence regression additionally combines a hidden symbol-keyed ASK receipt on the BID-only archive with hostile optional cost and source proxies. At a valid completed-hour cutoff, the undeclared receipt must be rejected without invoking any receipt, cost or provenance getter. This only verifies fail-closed schema validation order; it cannot establish authentic broker quotes, licensed history or profitability.


Binary array views (including `Uint8Array` and `DataView`) are not candle archives. A synthetic valid-cutoff regression requires the as-of scanner to reject them before optional cost configuration or source-provenance inspection. Numeric bytes cannot substitute for timestamped, completed OHLC candles; this does not validate actual feed provenance or trading returns.

Iterable archive impostors (a custom lazy iterable, `Set`, `Map`, or string) are also invalid inputs to the causal 1H FVG BID-only study. A synthetic valid-cutoff regression requires rejection before executing an iterator getter or inspecting optional cost/source metadata. This is an input-schema and no-side-effect test, not authentication of real candles, volume, broker quotes or trading performance.

A completed-hour timestamp must now be an own **data property** in causal as-of research. An accessor-backed completed timestamp could change its private return value after its single read while preserving the same descriptor, defeating snapshot stability. A synthetic regression rejects it before any later future-time accessor executes; a normal completed data-property timestamp with a future timestamp-only accessor remains supported, and future OHLC/volume/coverage stays unread. This is a causal input-integrity rule, not independently authenticated market data, source-classified volume, executable BID/ASK quotes, or a profitable trading strategy. Verify exact-head CI before review.

A synthetic later-row regression now checks that an accessor-backed timestamp on the **second completed hour** fails closed before the scanner reads even a later future timestamp, much less future OHLC/volume/coverage. This complements the first-completed-row test and confirms chronological early rejection across a nonempty completed prefix. It is a software causality regression only, not market-data provenance, broker quote verification, or performance evidence.

A final completed-hour regression also rejects an accessor-backed timestamp when the archive contains **no future row at all**. The causal snapshot requirement applies to every completed row, not only when future evidence is present. This synthetic test does not authenticate historical prices, source-classified volume, broker quotes or profitability.

A synthetic inherited-timestamp regression rejects a completed hourly candle whose `time` exists only on its prototype. The inherited getter must not run, and no future timestamp, OHLC, volume or coverage getter may run. Only an own timestamp field can supply completed-bar evidence; this does not verify market data or strategy profitability.

A separate synthetic regression checks a prototype-inherited **plain data** timestamp (not a getter). The completed candle is rejected before reading a later future timestamp. This complements inherited-getter coverage and prevents prototype defaults from counting as observed completed-hour evidence; it does not establish licensed market data, quote authenticity, or profitability.

A later completed-hour regression now supplies a prototype-inherited timestamp getter on the **second** completed candle, after a valid first row and before a hostile future row. The scanner must reject missing own timestamp evidence without invoking either getter. This tests early causal rejection in a multirow prefix only; it does not authenticate historical data, broker quotes, source-classified volume or profitability.

A second-completed-hour synthetic regression also rejects a prototype-inherited **plain data** timestamp (as opposed to an inherited getter) after a valid first candle. A hostile later future candle must remain entirely unread, including its timestamp and OHLC/volume/coverage getters. This verifies that chronological progress does not turn inherited defaults into observed source evidence; it does not authenticate prices, volume, broker quotes or returns.

A positive-control synthetic regression also accepts a completed 1H candle with an **own plain-data timestamp on a null-prototype object**. The as-of study observes that completed candle without reading future OHLC, volume or coverage getters. The safeguard rejects inherited or accessor-backed timestamp evidence, not legitimate own-data records merely because they have no prototype. This does not authenticate source data or establish trading performance.

A two-completed-hour positive-control regression now accepts a **second** own plain-data timestamp on a null-prototype candle after a normal first candle. The as-of scanner must count both completed rows and leave future OHLC, volume and coverage accessors unread. This complements second-row inherited/accessor rejection and guards against an overbroad rule that would discard valid source-shaped records. Synthetic only: no authenticated market source, broker quote or profitability evidence.

A synthetic future-time mutation regression in `frontend/tests/hourly-fvg-future-time-mutation.test.ts` checks that reading an unrevealed future candle's timestamp cannot rewrite the **second completed candle's own-data timestamp** without detection. The as-of scanner must reject the changed descriptor value after the timestamp-only ordering scan, while never reading future OHLC, volume or coverage. This tests snapshot consistency only; the fixture does not certify source data, broker quotes, fills or profitability.

A companion synthetic regression checks mutation of the **first** completed candle timestamp by an unrevealed future candle's timestamp getter (the second completed candle was already covered). The as-of declaration snapshot must detect the mutation and fail closed without inspecting future OHLC, volume or coverage. This is an adversarial in-memory integrity test, not a historical market receipt or evidence of profitability.

A synthetic prior-volume mutation regression checks that a future candle's timestamp-only getter cannot rewrite an already completed candle's volume evidence. The as-of scan must reject the changed completed-field descriptor before reading any future OHLC, volume or coverage getter. This is an in-memory causal integrity check, **not** verified exchange/tick volume provenance or evidence of profitable execution.

A synthetic regression also changes the **second completed hour's observed-minute coverage** through a future timestamp getter. The as-of snapshot must reject the changed coverage descriptor without reading future OHLC, volume or coverage. This protects completed-bar eligibility metadata, not source authenticity or trading performance.
