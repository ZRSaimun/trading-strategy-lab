# Boolean pending-hour timestamp regression

The synthetic test `frontend/tests/hourly-fvg-boolean-pending-timestamp.test.ts` supplies a valid first unrevealed 1H timestamp, followed by `true` as the second pending timestamp. The causal 1H FVG as-of preflight must reject the boolean rather than coerce it to a number. It must stop before inspecting the third pending timestamp and must not access any unrevealed OHLC, volume, or minute-coverage getters.

This guards strict timestamp typing and the no-lookahead boundary only. It does **not** verify source identity, authenticated prior-20 volume, real broker BID/ASK quotes, news/calendar provenance, or strategy profitability. CI must be verified against the exact updated PR head before marking this regression passed. No live trading or deployment is authorized.
