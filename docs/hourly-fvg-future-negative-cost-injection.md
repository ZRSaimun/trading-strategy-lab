# Future timestamp negative-cost injection regression

The causal 1H FVG midpoint research study freezes the declared hypothetical round-trip cost scenarios before inspecting unrevealed future timestamps. A malicious or mutable timestamp accessor can change the second scenario from 5 bps to -5 bps while the first future timestamp is read. Negative costs could misleadingly inflate modeled net BID markouts.

`frontend/tests/hourly-fvg-future-negative-cost-injection.test.ts` requires the scanner to reject that mutation immediately, without examining the second future timestamp or reading any future OHLC, volume or observed-minute coverage. The fixture has explicitly unverified volume and makes no claim of authentic market data.

This is a synthetic causality and input-integrity regression, not a test of broker fills, realistic spreads, verified quote-side costs, execution profitability, or market-data licensing. Production validation still requires authorized source-classified prior-20 volume, actual two-sided demo quotes and held-out data.
