# Completed hourly open mutation at an unrevealed future timestamp

The 1H FVG as-of scanner must not allow a future-row timestamp accessor to
rewrite the **open** of an already completed candle. An opening price is part
of the frozen source snapshot even if a particular FVG formation condition
uses other OHLC fields more directly.

The synthetic regression in
`frontend/tests/hourly-fvg-future-completed-open-mutation.test.ts`
uses an as-of boundary at 2 hours, two completed hourly bars, and two
unrevealed future rows. The first future timestamp accessor changes the
first completed bar's open from 100 to 100.5. The scanner must reject this
as a completed-candle snapshot integrity violation **before** reading the
second future timestamp or any future OHLC, volume, or minute-coverage field.

This is a deterministic mutation/causality test, not market data, a
validated provider receipt, evidence of executable BID/ASK fills, or
evidence of strategy profitability. Actual source-classified volume,
licensed held-out histories, broker costs and economic calendars remain
unverified.
