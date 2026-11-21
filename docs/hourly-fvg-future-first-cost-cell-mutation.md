# 1H FVG as-of: first cost-cell mutation boundary

The research-only causal 1H FVG scanner must preserve the exact declared hypothetical transaction-cost array during its permitted future-timestamp inspection. A future timestamp getter that changes **the first** scenario from 0 to 5 bps must cause immediate rejection, before a second future timestamp or any future OHLC, volume, or minute coverage is accessed.

`frontend/tests/hourly-fvg-future-first-cost-cell-mutation.test.ts` provides this synthetic case as a complement to the existing second-cost-cell mutation regression. It checks both short-circuit ordering and that the source remains explicitly unverified. The test does not establish that the quoted hypothetical bps are realistic: actual broker BID/ASK demo quotes, spread/financing evidence, authenticated source-classified volume, and held-out validation remain missing.

This is paper-only input integrity testing, not an execution path, broker validation, market price evidence, or profitability claim.
