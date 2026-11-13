# Pending-hour source declaration seal regression

The causal 1H FVG as-of study must reject a pending (not yet closed) hourly candle whose timestamp accessor irreversibly changes the property descriptor of an already-declared source identity field. This includes dataset ID, archive SHA-256, instrument, provider, BID side, declared volume type, and the volume-verification flag. Even if the value is unchanged, the source declaration's representation changed *after* the completed prefix was read.

`frontend/tests/hourly-fvg-pending-source-seal.test.ts` supplies fifty-six synthetic mutation cases plus two non-mutating controls (seven fields × four descriptor variants, seven deletion cases, and seven value-rewrite cases). Two variants permanently make one source field non-configurable, either retaining writability or also making it non-writable. A third variant retains configurability but removes writability during exactly one future timestamp read. A fourth variant makes the field non-enumerable while leaving it configurable and writable, hiding the declared identity from ordinary serialization. All four alter the snapshotted declaration without changing its value. Seven additional cases delete an own source field during the pending-hour timestamp read, without substituting an inherited value. These must fail closed as well, before any future market field is accessed. The scan must fail closed without reading any future OHLC, volume, or minute-coverage field. An irreversible mutation cannot be undone in place; callers must reconstruct the declaration from independent evidence before retrying. Even a technically reversible descriptor change must not be silently accepted as unchanged provenance.

Seven prototype-substitution cases remove an own source field and supply an inherited field of the same value during the pending timestamp read. Even matching inherited values are not an authenticated own declaration; the scan must reject them before future OHLC, volume or coverage reads.

Seven further cases rewrite an already-snapshotted source value during the pending timestamp getter, including a changed dataset hash, provider, declared price side, and volume-verification status. These must reject the stale snapshot before reading any pending market values, even where the replacement value is otherwise well-formed. The intentionally invalid ASK declaration is never accepted as a valid BID source.

These tests establish only in-memory declaration consistency. They do not verify a volume provider, license, raw source receipt, BID/ASK quote, execution cost, fill, trading outcome, or profitability. Keep the study draft, paper-only, unmerged and undeployed pending exact-head CI and independent evidence.

## Pending-hour data-to-accessor source substitution

Seven additional synthetic regressions cover replacing each previously snapshotted own source-identity data field with an enumerable accessor returning the same value. The as-of scan must reject the descriptor-type mutation after exactly one pending timestamp read, without invoking the replacement source getter or any future OHLC, volume or minute-coverage getter. Matching returned values cannot authenticate a changed evidence declaration. This is an integrity regression, not verification of real source receipts, broker execution or profitability.

## Valid pending-hour and strictly future-hour controls

A non-mutating pending timestamp accessor is accepted as an ordinary as-of boundary. The synthetic control asserts that the pending timestamp is read once and pending OHLC, volume and observed-minute accessors are never invoked. This prevents the mutation rejection tests from passing merely because the scanner rejects every pending timestamp. This control is not a real-data or profitable-strategy validation.

A second non-mutating synthetic control places the last hourly timestamp strictly after the as-of cutoff. It verifies the scanner reads that timestamp once, skips the future bar, and never invokes its OHLC, volume, or minute-coverage accessors. This is a causal boundary check, not source authentication or trading-performance evidence.
