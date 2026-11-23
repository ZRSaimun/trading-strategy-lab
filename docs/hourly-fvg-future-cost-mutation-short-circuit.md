# 1H FVG as-of: future cost mutation short-circuit

The causal as-of scanner snapshots the declared hypothetical round-trip cost scenarios before inspecting unrevealed future timestamps. After **each** timestamp read it now checks that study settings and every declared cost cell still match that snapshot, rather than waiting until the entire future timestamp scan finishes.

The synthetic regression `frontend/tests/hourly-fvg-future-cost-mutation-short-circuit.test.ts` mutates the second cost cell from 10 to 20 bps inside the first future timestamp getter. It requires immediate rejection, no second future timestamp read and no future OHLC, volume or observed-minute access. This prevents a later accessor from executing after an earlier one invalidated the hypothetical cost evidence.

These costs are illustrative and not actual two-sided broker quotes. The test is a software integrity check, not source authentication, evidence of executable fills, an edge or profitability. No market data, order routes or live service is introduced.
