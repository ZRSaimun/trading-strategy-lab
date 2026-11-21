# Second unrevealed future row: completed-source integrity

The causal 1H FVG as-of scanner must treat later, unrevealed hourly rows as timestamp ordering metadata only. A first future row that leaves the source declaration unchanged must not create a loophole for a **second** future timestamp getter to mutate the completed-prefix archive SHA-256 identity.

`frontend/tests/hourly-fvg-second-future-row-source-mutation.test.ts` uses synthetic two-hour completed history, then two unrevealed rows. The second timestamp accessor changes `archiveSha256`; the scanner must reject the source snapshot with the specific integrity error. Both future timestamps are inspected once, and neither future row's OHLC, volume or minute coverage may be read. The volume declaration remains unverified.

This regression tests causal metadata isolation only. It does not authenticate the dataset hash, volume source, licensed market prices, two-sided broker quotes, execution, performance or profitability. Keep paper-only; no trading, merge or deployment is authorized by this test.
