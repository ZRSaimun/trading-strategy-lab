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

A companion synthetic test now checks the **first** completed hour's observed-minute coverage against mutation triggered by an unrevealed future timestamp getter. The as-of scan must fail closed without reading future market fields. This is snapshot integrity, not independently verified historical coverage or profitability.

A synthetic completed-close mutation regression checks that an unrevealed future candle's timestamp getter cannot alter the second completed 1H candle's closing price while preserving its apparent historical eligibility. The scanner must fail closed before reading any future OHLC, volume or coverage getter. This verifies in-memory snapshot integrity only, not market provenance, broker execution or profitability.

A synthetic first-completed-hour closing-price mutation regression complements the second-hour close guard: an unrevealed future candle's timestamp getter may be read only for ordering, and cannot rewrite earlier completed closing-price evidence without a fail-closed snapshot error. Future OHLC, volume and coverage getters must remain unread. This tests in-memory integrity, not authentic feed provenance, executable quotes or strategy profitability.

A companion synthetic regression checks that an unrevealed future timestamp getter cannot rewrite the **second completed 1H candle's volume** while leaving future OHLC, volume and coverage unread. This closes the second-row counterpart of the earlier first-row volume mutation test. A rejected in-memory mutation does not authenticate source-classified volume or demonstrate trading performance.

A synthetic FVG-boundary regression additionally rejects a future timestamp getter that rewrites the **first completed hour's high**, a price used in gap geometry. The completed-field snapshot must fail closed while future OHLC, volume and coverage getters remain unread. This checks in-memory causal integrity only; it is not authenticated BID/ASK, volume provenance, or profitability evidence.

A synthetic second-completed-hour **low-price** mutation regression complements the first-hour high-price test. A future timestamp getter that rewrites the second completed candle's FVG geometry must trigger a snapshot rejection, without reading future OHLC, volume or coverage. This is a causal software-integrity check only; source authenticity, two-sided execution prices and profitability remain unverified.

A synthetic failure-path regression now requires an unrevealed future candle whose `time` accessor throws to abort the causal scan rather than attempt to recover using future OHLC, volume, or minute-coverage fields. The test checks one timestamp attempt and zero future market-field reads. It is a software fail-closed contract, not a market-data receipt or strategy validation.

A synthetic multi-pending regression checks that when the first unrevealed candle's timestamp getter throws, the causal scan aborts without invoking any later pending candle getters or future OHLC/volume/coverage getters. The archive may inspect own-property descriptors during schema preflight; this is distinct from executing getters. This tests fail-closed sequencing, not historical source authenticity or profitability.

A synthetic second-pending timestamp failure regression (`frontend/tests/hourly-fvg-second-pending-failure.test.ts`) verifies that after one valid unrevealed timestamp, a later pending timestamp accessor throwing aborts the scan before inspecting subsequent pending timestamps or any pending market/coverage fields. This is a fail-closed ordering guarantee, not proof of source authenticity, execution, or profitability.

A further synthetic regression extends pending-timestamp failure ordering to the **third** unrevealed row: the first two pending timestamps are read once, the third throws, and the fourth is never inspected. No pending OHLC, volume or coverage getter may execute. This guards against a later-row scan continuing after a timestamp failure; it does not authenticate prices, quotes, volume or profitability.

A fourth-pending-row synthetic failure regression checks the same fail-closed ordering beyond the third pending timestamp: the first four pending timestamp accessors run once, the fourth throws, the fifth remains unread, and no pending OHLC, volume or observed-minute coverage getter runs. This is an in-memory causal ordering check, not verified market data, execution evidence or profitability. Exact-head CI must be checked before review.

A synthetic invalid-value regression now checks that a **second pending future timestamp returning `NaN`** is rejected immediately, without invoking the third pending timestamp or any future OHLC, volume or coverage getter. Unlike the earlier throwing-accessor cases, this exercises explicit timestamp validation and prevents an invalid future row from being skipped as missing data. It is not a real market-data receipt or profitability evidence. Exact-head CI remains to be verified.

A synthetic pending-row regression also rejects positive infinity as the second unrevealed hourly timestamp, stopping before a third pending timestamp or any future OHLC, volume or coverage getter is read. This complements NaN rejection and checks finite-number validation only; it is not a verified market-data, broker-execution or profitability result.

A companion synthetic regression rejects negative infinity in the second pending future-hour timestamp, stopping before the third timestamp or any future OHLC, volume or coverage getter executes. Both signs of infinity now have explicit pending-row tests. This is input-integrity coverage, not authenticated market evidence, realistic broker costs or profitability.

## Duplicate unrevealed timestamp regression (18 November 2026)

A synthetic test in `frontend/tests/hourly-fvg-second-pending-failure.test.ts` supplies a second pending 1H timestamp equal to the first pending timestamp. The as-of scanner must reject the non-increasing archive ordering before invoking any later pending timestamp or any future OHLC, volume, or minute-coverage getter. This validates causal input ordering only; no authenticated market source, execution quote, or trading performance is inferred.

## Descending unrevealed timestamp regression (18 November 2026)

A synthetic regression in `frontend/tests/hourly-fvg-second-pending-failure.test.ts` now supplies a second pending hourly timestamp that is strictly **earlier** than the first pending timestamp, rather than merely equal to it. The causal as-of scanner must reject the archive immediately, without evaluating a third pending timestamp or reading any pending OHLC, volume, or observed-minute coverage getter. This guards chronological input integrity; it does not verify licensed price history, authentic two-sided broker quotes, source-classified volume, execution, or profitability.

## Valid future timestamp positive control (18 November 2026)

A synthetic positive control in `frontend/tests/hourly-fvg-second-pending-failure.test.ts` supplies three strictly increasing unrevealed 1H timestamps after two completed hours. The as-of scanner must accept timestamp ordering, count only the two completed bars in coverage, and never read pending OHLC, volume or observed-minute coverage accessors. This complements the malformed/duplicate/descending failure tests and prevents an overstrict preflight from rejecting a well-ordered archive merely because future price getters are unavailable. Timestamp ordering is not independent source authentication, broker execution evidence or profitability validation.

A synthetic cutoff-boundary regression checks that a 1H candle **opening exactly at the as-of cutoff** is not yet completed: its timestamp may be inspected once for chronology, but its OHLC, volume and observed-minute getters remain unread. Only earlier closed candles contribute to coverage. This is a no-lookahead invariant, not a verified broker feed or trading result.


A complementary synthetic cutoff-boundary regression verifies that an hourly candle opening at `2*3600` UTC seconds **is completed** at the `3*3600` cutoff and contributes to observed-bar coverage, while a candle opening exactly at `3*3600` remains unrevealed. Only the future timestamp may be read for ordering; future OHLC, volume and minute coverage must remain unread. This tests closed-bar inclusion without asserting genuine market evidence or profitability.

A synthetic pending-candle regression also rejects a fractional, off-hour future timestamp (for example, `14400.5` seconds) after one valid unrevealed hour. The scanner must stop before reading any subsequent pending timestamp or any unrevealed OHLC, volume, or minute-coverage field. This tests chronological hourly archive integrity, not independently sourced timestamps or trading performance. Exact-head CI must be checked separately.


## Numeric-string pending timestamp rejection (18 November 2026)

A synthetic regression supplies a second unrevealed hourly timestamp as the string `"14400"`, rather than a numeric UTC-second value. The causal preflight must reject this coercible representation before inspecting any later pending timestamp or any unrevealed OHLC, volume or observed-minute coverage getter. This prevents silent timestamp type coercion from being mistaken for validated source chronology. It does not establish authenticated market-data provenance, broker quote execution or profitability.

A synthetic second-pending-hour regression rejects a timestamp beyond the inclusive 2100-01-01 UTC research horizon before inspecting the third pending timestamp or any unrevealed OHLC, volume or observed-minute coverage. This protects the bounded UTC timestamp schema; it does not certify market-data provenance, execution or strategy returns.

A second-pending-row signed-zero regression rejects IEEE-754 `-0` as an unrevealed 1H timestamp, even after an earlier valid pending timestamp. The scan must stop before the third pending timestamp and must never evaluate future OHLC, volume or minute-coverage getters. This is a synthetic temporal-integrity check only, not authenticated feed evidence or a trading-performance result.

A synthetic pending-row regression also rejects a `bigint` future 1H timestamp even when its numeric magnitude is hour-aligned. It verifies chronological scanning halts before later future timestamps or unrevealed OHLC, volume and coverage getters. This tests strict runtime typing and causal access only, not broker/source authenticity or strategy profitability.


A synthetic regression rejects an object-wrapped `Number` timestamp on the second pending hourly candle, even when its value is aligned to an hour. The causal preflight must not coerce object wrappers, inspect a third pending timestamp, or read unrevealed market/coverage fields. This guards runtime type integrity only, not source authenticity, execution, or profitability.


A synthetic second-pending-candle regression rejects a coercible object timestamp without invoking `Symbol.toPrimitive`, `valueOf`, or `toString`, and without reading any later pending timestamp or unrevealed OHLC/volume/coverage getters. It checks fail-closed runtime validation and side-effect ordering, not verified source identities, broker quotes, or trading profitability.

A positive boundary regression accepts an unrevealed future hourly timestamp exactly at the inclusive 2100-01-01 UTC research horizon, while excluding that candle from completed coverage and never reading its OHLC, volume or minute-coverage fields. This complements the beyond-horizon rejection case and prevents accidental off-by-one tightening. It is synthetic chronological validation, not a source receipt or trading result.

A paired horizon-ordering regression accepts the first unrevealed timestamp at 2100-01-01 UTC but rejects the immediately following hour as out of the supported range. The scan must not read the third pending timestamp or any unrevealed OHLC, volume, or minute-coverage field. The synthetic fixture tests chronological validation only; it cannot certify market-data authenticity or strategy returns.


## Null second pending timestamp (19 November 2026)

A synthetic as-of regression rejects a `null` timestamp on the second unrevealed 1H candle after one valid pending timestamp. The scanner must not coerce `null` to numeric zero, read a later pending timestamp, or access unrevealed OHLC, volume or minute-coverage fields. This tests fail-closed chronological evidence handling only; it does not authenticate a source, prove execution costs, or demonstrate profitability.

A synthetic positive-control regression also attaches a hostile, non-enumerable `askQuotes` getter to an unrevealed hourly candle. The as-of scanner may inspect that candle's timestamp once for chronological validation, but must not enumerate or invoke the ASK receipt or any future OHLC, volume or coverage getter. This does not supply real two-sided broker quotes or authenticate source provenance; it protects the completed-bar evidence boundary only.


## Completed coverage mutation guard (19 November 2026)

A synthetic regression in `frontend/tests/hourly-fvg-second-pending-failure.test.ts` supplies a future timestamp accessor that changes the first *completed* 1H candle's `observed_minutes` from 60 to 0. The causal scanner must reject the altered completed-bar snapshot rather than silently recalculate coverage using a value introduced after the as-of cutoff. Only the future timestamp may be read; future OHLC, volume and minute-coverage accessors must stay unread. This tests in-memory no-lookahead integrity, not the authenticity of volume, broker BID/ASK quotes, licensed history or trading performance. CI must be verified against the exact updated PR head.


A companion synthetic regression protects the **second** completed 1H candle's `observed_minutes` from modification by a future candle timestamp getter. The scan must reject the changed completed snapshot while reading no unrevealed OHLC, volume or coverage getters. This closes the later-row coverage counterpart to the first-row test; it does not establish licensed data provenance, genuine volume, broker execution or profitable results. Exact-head CI must be checked independently.

A synthetic regression additionally checks the **second completed hour's open price** against mutation by a future candle's timestamp getter. The scanner must reject a changed completed-bar snapshot while never reading unrevealed OHLC, volume or minute coverage. This is an in-memory causal-integrity check, not verified source data, broker quotes, or evidence of profitable trading. Exact-head CI must be checked independently.


## Completed timestamp mutation regression (19 November 2026)

`frontend/tests/hourly-fvg-completed-time-mutation.test.ts` checks that a future 1H timestamp accessor cannot rewrite a previously completed candle's UTC timestamp after the causal snapshot is established. The scan must reject the mutation without reading any unrevealed OHLC, volume or coverage getter. This is synthetic in-memory chronology integrity, not licensed market data, authentic source-classified volume, two-sided broker execution or profitability evidence.

A focused synthetic regression in `frontend/tests/hourly-fvg-completed-close-mutation.test.ts` rejects a pending timestamp getter that retroactively changes the second completed BID candle's `close` while leaving its OHLC otherwise valid. The scanner must reject the completed snapshot before reading later future timestamps or any unrevealed market fields. This guards causal input integrity only; it does not verify broker quotes, volume receipts, or profitability.


## 19 November 2026 — completed-close mutation CI repair

The synthetic completed-BID-close mutation regression now distinguishes timestamp-only pending-candle preflight from completed-field snapshot revalidation. The scanner may inspect **both** pending timestamps before it detects an earlier completed candle's in-place close rewrite, but must reject the mutated completed snapshot and must **not** read pending OHLC, volume or observed-minute fields. Previous test expected the second pending timestamp to remain unread; exact-head frontend CI showed that assertion was incompatible with the existing timestamp-only preflight ordering (1,475/1,476 tests passed). This correction does not authenticate real data or establish strategy profitability.


## Completed hourly volume mutation regression (19 November 2026)

`frontend/tests/hourly-fvg-completed-volume-mutation.test.ts` supplies a future timestamp getter that changes the second completed hourly candle's volume from 10 to 11 after the as-of snapshot. The causal scanner must reject the changed completed evidence and must not read future OHLC, volume or observed-minute fields. This synthetic check prevents retroactive in-memory volume changes from being silently accepted; it does **not** verify volume source identity, authentic volume receipts, broker quotes or profitability. Exact-head CI must be checked before treating this regression as verified.


## First completed-hour volume snapshot regression (19 November 2026)

`frontend/tests/hourly-fvg-first-completed-volume-mutation.test.ts` checks that timestamp-only inspection of an unrevealed hourly bar cannot alter the first already-completed bar's numeric volume without a fail-closed snapshot-integrity rejection. The future OHLC, volume and coverage getters must remain unread. This is synthetic in-memory mutation protection; it does not verify a volume provider, classify exchange versus tick volume, or demonstrate any trading edge. Exact-head CI must be checked independently.


## First completed-hour low geometry mutation (19 November 2026)

`frontend/tests/hourly-fvg-first-completed-low-mutation.test.ts` checks that an unrevealed future hourly timestamp getter cannot revise the first completed BID candle's `low` from 99 to 98.5 (still valid OHLC) without an as-of snapshot-integrity rejection. The timestamp-only chronology preflight is permitted, but no future OHLC, volume or coverage getter may run. This closes a first-row FVG-geometry mutation regression gap; it does not authenticate the underlying BID source, volume, broker fills or trading profitability. Verify CI against the exact updated PR head.


## First completed-hour high geometry mutation (19 November 2026)

`frontend/tests/hourly-fvg-first-completed-high-mutation.test.ts` rejects a pending hourly timestamp accessor that changes the first already-completed BID candle's `high` from 101 to 101.5 while preserving otherwise valid OHLC. Only the unrevealed timestamp may be inspected for ordering; unrevealed OHLC, volume and minute coverage must not be read. This complements the completed-low mutation regression and tests in-memory snapshot integrity only. It does not authenticate BID prices, source-classified volume, broker quotes, executable fills or profitability. Verify the exact PR head in CI.


A synthetic regression in `frontend/tests/hourly-fvg-second-completed-high-mutation.test.ts` requires the causal as-of scanner to reject a future timestamp accessor that changes the **second completed hourly BID candle's high** after the completed-prefix snapshot. Future OHLC, volume and coverage getters remain unread. This guards FVG geometry against retroactive mutation; it does not validate authentic market data, broker fills or strategy profitability. Exact-head CI must be checked separately.


## Second completed-hour low geometry mutation (19 November 2026)

`frontend/tests/hourly-fvg-second-completed-low-mutation.test.ts` checks that a future hourly timestamp accessor cannot change the second completed BID candle's `low` from 99 to 98.5 while retaining valid OHLC. The causal as-of scanner must reject the revised completed-bar snapshot, without reading unrevealed OHLC, volume or minute coverage. This complements the second completed-hour high regression and protects only in-memory no-lookahead integrity. It does not authenticate volume provenance, broker BID/ASK execution, licensed historical data or profitability. Exact-head CI must be checked independently.


## Completed minute-coverage integrity during future timestamp preflight (19 November 2026)

`frontend/tests/hourly-fvg-second-completed-coverage-mutation.test.ts` supplies a synthetic future candle whose timestamp getter changes the second completed hourly BID candle's `observed_minutes` from 60 to 59. The as-of scanner must reject the altered completed snapshot, while reading no unrevealed future OHLC, volume, or minute-coverage fields. This tests a local causal integrity boundary only. It does not prove real minute coverage, source identity, authentic volume, broker costs, strategy edge, or profitability; exact-head CI must be checked separately.


## First-completed-hour coverage mutation regression (19 November 2026)

`frontend/tests/hourly-fvg-first-completed-coverage-mutation.test.ts` supplies two completed hourly BID candles and an unrevealed future timestamp accessor that mutates the **first** completed candle's observed-minute coverage from 60 to 59. The causal scanner must reject the completed-prefix snapshot change, while never reading future OHLC, volume or coverage. This complements the second-completed-hour coverage regression and verifies software snapshot integrity only. It is not proof of authentic source volume, licensed market history, broker quotes, costs or profitability. Exact-head CI must be checked independently.

A synthetic regression in `frontend/tests/hourly-fvg-second-completed-open-mutation.test.ts` verifies that inspecting an unrevealed hourly timestamp cannot retroactively alter the second completed BID candle's opening price without a snapshot-integrity rejection. The unrevealed candle's OHLC, volume and coverage accessors must remain unread. This is causal software validation only, not proof of a genuine price feed, broker execution, or profitable FVG behavior.


The synthetic `hourly-fvg-first-completed-open-mutation.test.ts` regression checks that reading only an unrevealed future candle's timestamp cannot retroactively change the **first completed hourly BID open** without a completed-prefix snapshot-integrity rejection. The future candle's OHLC, volume and minute-coverage getters must not execute. This complements the second-completed-open case and is a software causal-integrity check only; it is not authenticated price, volume, broker execution or profitability evidence.


## First completed-hour close mutation regression (19 November 2026)

`frontend/tests/hourly-fvg-first-completed-close-mutation.test.ts` checks that a future hourly timestamp getter cannot retroactively rewrite the **first completed BID candle's close** from 100 to 100.5 while retaining valid OHLC. The as-of scanner must fail closed on completed-prefix snapshot integrity; future OHLC, volume and minute-coverage getters must remain unread. This complements the second-completed-close regression and establishes only synthetic causal input integrity, not authentic market prices, source-classified volume, broker BID/ASK execution, or trading profitability. Verify exact-head CI before claiming the regression passes.


## Second completed-hour close mutation regression (19 November 2026)

`frontend/tests/hourly-fvg-second-completed-close-mutation.test.ts` supplies two completed hourly BID candles and a future timestamp getter that changes the **second** completed candle's close from 100 to 100.5 while keeping OHLC valid. The causal scanner must reject the revised completed-prefix snapshot, without reading any future OHLC, volume or observed-minute getter. This complements the first completed-hour close regression. It tests in-memory integrity only, not real data provenance, broker quotes, performance or profitability. Exact-head CI must be verified separately.


A synthetic third-completed-candle regression (`frontend/tests/hourly-fvg-third-completed-volume-mutation.test.ts`) verifies that a future timestamp accessor cannot retroactively change the completed third hourly BID candle's volume after its prefix snapshot. The scanner must fail closed without reading future OHLC, volume or minute coverage. This protects the formation bar's source-declared numeric evidence against time-of-check/time-of-use mutation; it does **not** verify volume-source identity, independent market receipts, broker quotes or trading performance.

A synthetic third-completed-bar minute-coverage mutation regression (`frontend/tests/hourly-fvg-third-completed-coverage-mutation.test.ts`) verifies that an unrevealed future timestamp getter cannot revise the last completed BID candle from 60 observed minutes to 59 while remaining unnoticed. The scanner must reject the altered snapshot without reading future OHLC, volume, or coverage fields. This tests in-process consistency only; it does not authenticate archive coverage or establish any trading edge.
