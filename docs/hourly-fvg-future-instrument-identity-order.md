# Causal instrument identity rejection ordering

The 1H FVG as-of scanner must reject a completed-prefix source declaration if an unrevealed future timestamp accessor retroactively changes its instrument identity. The synthetic regression in `frontend/tests/hourly-fvg-future-instrument-identity-mutation.test.ts` now checks that rejection happens **before a second future timestamp getter**, and before any unrevealed OHLC, volume or coverage getter. This extends the prior one-future-candle test without changing the trading hypothesis or claiming an independent source identity receipt.

A passing regression demonstrates only fail-closed software behavior against this crafted mutation. It does not authenticate provider/instrument mapping, exchange volume, two-sided broker quotes, licensed market data, execution costs, or profitability. Keep paper-only, draft, unmerged and undeployed pending independent review.
