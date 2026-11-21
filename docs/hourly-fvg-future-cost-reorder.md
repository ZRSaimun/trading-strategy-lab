# Future timestamp cost-scenario reordering regression

The causal 1H FVG as-of scanner freezes its hypothetical round-trip cost scenarios before inspecting unrevealed future timestamps. A future timestamp getter that reverses the existing finite scenario array must be rejected immediately, before a second future timestamp or any future OHLC, volume, or minute-coverage property is accessed.

Regression: `frontend/tests/hourly-fvg-future-cost-reorder.test.ts`. The fixture uses synthetic bars and unverified volume. Reordering does not introduce a new numeric value, so this tests order integrity separately from cost-cell injection, truncation and nonfinite mutation. No real market source, broker execution quote, profitability, or strategy edge is established. Keep the study paper-only and the PR in draft until exact-head CI is verified.
