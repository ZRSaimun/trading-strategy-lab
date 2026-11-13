# Pending-hour source declaration seal regression

The causal 1H FVG as-of study must reject a pending (not yet closed) hourly candle whose timestamp accessor irreversibly changes the property descriptor of an already-declared source identity field. This includes dataset ID, archive SHA-256, instrument, provider, BID side, declared volume type, and the volume-verification flag. Even if the value is unchanged, the source declaration's representation changed *after* the completed prefix was read.

`frontend/tests/hourly-fvg-pending-source-seal.test.ts` supplies fourteen synthetic cases (seven fields × two descriptor variants). Each permanently makes one source field non-configurable, either retaining writability or also making it non-writable during exactly one future timestamp read. The scan must fail closed without reading any future OHLC, volume, or minute-coverage field. An irreversible mutation cannot be undone in place; callers must reconstruct the declaration from independent evidence before retrying.

These tests establish only in-memory declaration consistency. They do not verify a volume provider, license, raw source receipt, BID/ASK quote, execution cost, fill, trading outcome, or profitability. Keep the study draft, paper-only, unmerged and undeployed pending exact-head CI and independent evidence.
