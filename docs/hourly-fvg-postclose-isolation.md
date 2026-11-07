# Completed-hour bearish FVG evidence isolation

The standalone 1H FVG research treats a bearish first midpoint intersection as observable only after the intersecting hourly BID candle closes. The synthetic regression `frontend/tests/hourly-fvg-bearish-postclose-isolation.test.ts` records the first-touch result at its 24H close and verifies that appending a still-open future candle cannot change that earlier as-of result or read the future candle's OHLC, volume or minute-coverage fields. The completed-prefix full-history result must agree with the same as-of result.

The synthetic touch reports unusually large volume, but its declared source is **unverified**. Therefore `SOURCE_UNVERIFIED` and `INSUFFICIENT_DATA` remain mandatory and `eligibleForLiveTrading` remains false. This is a causal software regression, not independent validation of source identity, real volume, broker BID/ASK quotes, spread, fill probability or trading profitability. No orders, private datasets, credentials or deployment are involved.

## Bullish symmetry regression

`frontend/tests/hourly-fvg-bullish-postclose-isolation.test.ts` mirrors the post-close isolation check for a completed bullish gap and first midpoint touch. It compares the completed-prefix study with an as-of scan containing a later still-open candle whose OHLC, volume and observed-minute getters must never run. Unverified high reported volume remains insufficient evidence, and the study cannot authorize live trading. Both direction checks use synthetic BID-only prices; neither authenticates broker quotes, demonstrates an executable midpoint fill or measures profitability.

## Missing first eligible hour

The synthetic regression `frontend/tests/hourly-fvg-first-wait-gap-censor.test.ts` checks a bullish formation followed by a missing first eligible hourly BID bar and a later completed midpoint-intersecting bar. The later touch cannot erase the unknown earlier hour: the first-touch outcome stays `INCOMPLETE_WINDOW`, with `MISSING_HOUR` censoring observable only when the later bar closes. This prevents treating a discontinuous archive as a complete first-touch opportunity or a verified no-touch. It is not a broker execution or profitability test.
