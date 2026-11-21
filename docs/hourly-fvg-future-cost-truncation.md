# Causal 1H FVG: future cost-scenario truncation regression

A synthetic regression in `frontend/tests/hourly-fvg-future-cost-truncation.test.ts` checks that the first unrevealed future candle timestamp cannot shorten a previously declared hypothetical round-trip-cost array (three scenarios to two) before a second future timestamp is read. The as-of scanner must fail on the frozen cost-scenario schema and must not access future OHLC, volume or minute coverage. This protects the declared cost comparison population from retroactive changes during a timestamp scan; it does not authenticate the declared costs.

The test uses invented fixture candles solely for software verification. It supplies no licensed historical prices, independent source-classified volume receipts, executable two-sided broker quotes, session/news data, held-out performance, or evidence of profitability. Research remains paper-only; do not merge or deploy without separate approval.
