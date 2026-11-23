# Hourly FVG future volume-verification boundary

The synthetic regression `frontend/tests/hourly-fvg-future-volume-verification-boundary.test.ts` begins with a source declaring tick volume as **unverified**. A getter for the first unrevealed future timestamp changes `volumeVerified` to `true`. The causal as-of study must reject this source declaration mutation immediately, without reading the next future timestamp or any future OHLC, volume or observed-minute coverage.

This guards against retroactively promoting an unverified completed-prefix volume source to verified status during a future-only scan. The test uses artificial prices and deliberately adversarial JavaScript getters. Passing it does **not** authenticate a volume provider, prove the prior-20 volume threshold, establish actual broker BID/ASK execution prices or show profitability. Source-classified receipts, authorized market data, costs and untouched held-out evaluation remain required. Keep paper-only; do not merge or deploy without separate approval.

## Reverse transition regression (23 November 2026)

A second synthetic test starts with `volumeVerified: true` and changes it to `false` from the first unrevealed future timestamp getter. The causal as-of scan must fail immediately, read only that first future timestamp once, and never access the next timestamp or future candle payload. Both directions of a source-verification identity transition are prohibited after the completed-prefix declaration snapshot. This is a source-integrity invariant, not independent proof that the initial `true` declaration was authentic. Real licensed source receipts and two-sided broker quotes remain missing.
