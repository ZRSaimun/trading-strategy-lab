# Future-triggered completed-close mutation: causal 1H FVG regression

The synthetic regression `frontend/tests/hourly-fvg-future-completed-close-mutation.test.ts` supplies two completed 1H BID candles and two unrevealed future candles. The first future timestamp accessor changes the first completed candle's `close` from 100 to 100.5. The causal as-of scanner must reject this retroactive revision **before** reading the second future timestamp, and must never read future OHLC, volume or observed-minute coverage.

This is a point-in-time integrity test, not a market sample. It does not validate real source identities, authenticated prior-20 volume, actual broker BID/ASK spreads, financing, fill timing, a strategy win rate, or profitability. Unknown evidence remains insufficient. Keep the research paper-only, draft, unmerged and undeployed pending independent data verification.
