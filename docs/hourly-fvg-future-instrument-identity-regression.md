# Future timestamp cannot switch completed instrument identity

The synthetic regression `frontend/tests/hourly-fvg-future-instrument-identity-mutation.test.ts` exercises the research-only 1H FVG as-of scanner with two completed BID candles and one unrevealed future candle. Reading the future candle's timestamp attempts to change the frozen source instrument from synthetic Gold to synthetic Nasdaq. The scanner must reject the changed source declaration with its snapshot-integrity error, and must not read any future OHLC, volume, or minute-coverage getter.

Instrument identity is part of the evidence boundary: a completed prefix cannot be reinterpreted as another market after the fact. This regression does not verify source entitlement, authentic broker BID/ASK quotes, source-classified volume, economic calendars, real trading performance, or profitability. Keep the draft research-only, paper-only, unmerged, and undeployed pending review and independently licensed evidence.
