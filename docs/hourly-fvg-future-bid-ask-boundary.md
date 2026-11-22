# Causal hourly FVG BID/ASK identity boundary

The synthetic regression in `frontend/tests/hourly-fvg-future-bid-ask-boundary.test.ts` checks that a timestamp getter beyond the as-of boundary cannot silently switch the completed-prefix source declaration from BID to ASK. It must fail immediately after the first future timestamp, without reading the next timestamp or future OHLC, volume, or coverage. A stable BID declaration is the positive control: both future timestamps may be inspected, but their payload remains unrevealed.

This is a source-identity and no-lookahead contract, not evidence that the declared BID or ASK prices came from an authenticated broker. A BID-only archive cannot validate executable two-sided spread, financing, fill probability, source-classified volume, or profitability. Keep this research paper-only and draft until independent authorized receipts and held-out evaluation are available.
