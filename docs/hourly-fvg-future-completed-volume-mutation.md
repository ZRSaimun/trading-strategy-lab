# Completed-volume immutability during causal hourly FVG scans

A completed hourly BID candle's declared `volume` is part of the frozen as-of snapshot, even if its source is labelled `unverified` and cannot satisfy the prior-20 source-classified volume evidence gate. An unrevealed future timestamp getter must not revise that completed value before the scanner considers another future timestamp or reads future OHLC, volume, or coverage fields.

The synthetic regression `frontend/tests/hourly-fvg-future-completed-volume-mutation.test.ts` changes a completed volume from 10 to 20 while reading the first unrevealed timestamp. It requires immediate snapshot-integrity rejection and zero subsequent future reads. This is a fail-closed software invariant, not evidence of an authenticated source, actual market volume, trade execution, profitability, or statistical significance.

Outstanding research blockers include authenticated source-classified volume and identity receipts, actual broker two-sided BID/ASK demo quotes and costs, licensed multi-year untouched holdouts, and timestamped economic calendars. Keep PR draft, paper-only and undeployed; do not interpret missing evidence as a passing filter.
