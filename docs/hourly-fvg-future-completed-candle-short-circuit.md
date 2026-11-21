# Completed-candle integrity during future timestamp inspection

The causal 1H FVG as-of scanner may inspect unrevealed rows' timestamps for ordering, but must never inspect their OHLC, volume or coverage. After each timestamp read, it now rechecks the already completed candle field descriptors and schema before advancing. A future timestamp getter that retroactively changes a completed high fails immediately, without reading a second future timestamp.

Synthetic regression: `frontend/tests/hourly-fvg-future-completed-candle-short-circuit.test.ts`. This does not authenticate the dataset, broker quotes, volume provenance, execution, or profitability. All research remains paper-only and no missing evidence becomes a PASS.

## CI regression repair (21 November 2026)

The exact-head workflow for `75f5ce9` failed frontend (17 of 1,513 tests) after the new fail-fast guard: legacy completed-time mutation tests expected the prior `FVG as-of timestamp field changed during declaration snapshot` diagnostic, and a completed-close regression expected inspection of a later future timestamp. Preserve the earlier timestamp-specific error for completed `time` mutations while keeping the new generic completed-field diagnostic for OHLC/volume changes. Update the close regression to require zero later-future timestamp reads. This is a behavioral and compatibility repair; recheck exact-head CI before claiming success.
