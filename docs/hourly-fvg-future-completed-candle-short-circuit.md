# Completed-candle integrity during future timestamp inspection

The causal 1H FVG as-of scanner may inspect unrevealed rows' timestamps for ordering, but must never inspect their OHLC, volume or coverage. After each timestamp read, it now rechecks the already completed candle field descriptors and schema before advancing. A future timestamp getter that retroactively changes a completed high fails immediately, without reading a second future timestamp.

Synthetic regression: `frontend/tests/hourly-fvg-future-completed-candle-short-circuit.test.ts`. This does not authenticate the dataset, broker quotes, volume provenance, execution, or profitability. All research remains paper-only and no missing evidence becomes a PASS.
