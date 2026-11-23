# Multiple unrevealed future hourly rows: as-of regression

The synthetic regression `frontend/tests/hourly-fvg-multiple-unrevealed-future-rows.test.ts` supplies two completed BID hours and three later rows beyond the requested as-of boundary. Each later row has a readable timestamp but throws on any OHLC, volume, or minute-coverage access. The study must inspect ordering timestamps only, count exactly the two completed bars, and produce no fabricated formations or volume verification.

This tests an archive tail containing *several* future rows, rather than only one. It does not authenticate the source declaration, prove volume provenance, establish two-sided broker quotes, demonstrate executable fills, or measure profitability. Real source-licensed historical data and independent broker demo evidence remain prerequisites for trading-performance claims.
