# Future nonfinite hypothetical-cost injection guard

The causal 1H FVG midpoint scanner freezes research configuration before looking at unrevealed future candle timestamps. The synthetic regression `frontend/tests/hourly-fvg-future-nonfinite-cost-injection.test.ts` tests an adversarial first future timestamp getter that changes the first declared hypothetical round-trip cost from finite zero to `NaN`.

The scan must reject this change at the first timestamp boundary, without reading a second future timestamp or any future OHLC, volume, or minute-coverage fields. The test also verifies the mutation actually happened, so it cannot pass by silently avoiding the adversarial accessor.

These cost values are illustrative scenarios, not observed broker BID/ASK spreads or fills. This test is an integrity and no-lookahead regression, not evidence of trading profitability. Real source-classified volume receipts, broker demo two-sided quotes, licensed multi-year held-out histories, and timestamped economic/calendar sources remain outstanding. The PR stays draft, paper-only, unmerged, and undeployed.
