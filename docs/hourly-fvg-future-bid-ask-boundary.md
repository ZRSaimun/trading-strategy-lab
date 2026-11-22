# Causal hourly FVG BID/ASK identity boundary

The synthetic regression in `frontend/tests/hourly-fvg-future-bid-ask-boundary.test.ts` checks that a timestamp getter beyond the as-of boundary cannot silently switch the completed-prefix source declaration from BID to ASK. It must fail immediately after the first future timestamp, without reading the next timestamp or future OHLC, volume, or coverage. A stable BID declaration is the positive control: both future timestamps may be inspected, but their payload remains unrevealed.

This is a source-identity and no-lookahead contract, not evidence that the declared BID or ASK prices came from an authenticated broker. A BID-only archive cannot validate executable two-sided spread, financing, fill probability, source-classified volume, or profitability. Keep this research paper-only and draft until independent authorized receipts and held-out evaluation are available.

## Second future timestamp mutation regression (22 November 2026)

A synthetic three-future-bar control now mutates the source declaration from BID to ASK on the **second** future timestamp getter. The as-of scanner must reject the declaration change after exactly two timestamp reads, without inspecting the third future timestamp or any unrevealed OHLC, volume, or coverage field. This complements the first-timestamp rejection and stable-BID controls. It tests source-identity and no-lookahead behavior only; it does not authenticate broker quotes or establish strategy performance.

## Third future timestamp mutation regression (22 November 2026)

A four-future-bar synthetic fixture changes the source price side from BID to ASK on the **third** unrevealed timestamp getter. The causal scanner must reject the declaration change after exactly three timestamp reads; the fourth future timestamp and every unrevealed OHLC, volume and coverage getter must remain unread. This tests short-circuit ordering at a later boundary, not broker quote provenance, realistic costs, strategy edge or profitability. Keep draft, paper-only and undeployed.
