# Future-triggered completed-extreme mutation: causal 1H FVG regression

The synthetic regression `frontend/tests/hourly-fvg-future-completed-extreme-mutation.test.ts` checks both `high` and `low` on an already completed hourly BID candle. The first unrevealed future timestamp accessor attempts to revise that historical extreme. The as-of scanner must fail immediately before inspecting a second future timestamp, without reading future OHLC, volume or minute coverage.

High and low define the three-candle gap boundaries, so revising either after its close would invalidate the causal formation snapshot. These are deliberately adversarial in-memory fixtures, not market observations. The regression does not independently authenticate volume-source identities, demonstrate executable broker BID/ASK fills, establish historical win rates, or verify profitability. Maintain paper-only, draft and unmerged status until source evidence is independently checked.
