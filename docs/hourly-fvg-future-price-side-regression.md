# Future timestamp must not rewrite completed BID price-side evidence

The synthetic regression `frontend/tests/hourly-fvg-future-price-side-mutation.test.ts` passes two completed hourly BID candles and an unrevealed future candle into the causal 1H FVG as-of scanner. The future candle's timestamp getter tries to switch the completed source declaration from `bid` to `ask`. The scanner must raise the source-declaration snapshot-integrity error, with exactly one future timestamp read and no future OHLC, volume, or minute-coverage reads.

A BID-only historical archive cannot become a two-sided quote stream by retroactively changing a declaration. This regression tests a hostile in-memory accessor and does not establish authentic ASK quotes, spreads, slippage, broker financing, licensed volume provenance, market performance, or profitability. Keep this work draft, paper-only, unmerged, and undeployed pending independent evidence and review.
