# Causal 1H FVG: appended hypothetical cost scenario

The as-of study snapshots its hypothetical round-trip cost scenario population before inspecting unrevealed future timestamps. A future timestamp accessor must not append a plausible numeric cost (for example, 10 bps to an initial [0, 5] bps list) and let the scanner inspect the next future timestamp.

`frontend/tests/hourly-fvg-future-cost-append.test.ts` asserts immediate rejection, no second-future timestamp access and no future OHLC, volume or coverage reads. This complements the existing reorder/truncation and nonfinite-cost mutation checks. The fixtures are synthetic and exercise input integrity, not a broker fill or profitability.

All costs are illustrative. Real BID/ASK broker-demo quotes, verified source-classified prior-20 volume, licensed held-out candles and first-available calendar receipts remain missing. Keep this research paper-only; do not merge or deploy without separate approval.
