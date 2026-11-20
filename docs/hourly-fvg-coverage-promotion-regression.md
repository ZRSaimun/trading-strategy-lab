# Completed-hour coverage promotion regression

The causal 1H FVG as-of scanner must reject an archive whose second completed BID candle changes from unknown minute coverage (`null`) to apparently complete coverage (60 observed minutes) while the timestamp of a future, unrevealed candle is inspected. This guards against retroactive evidence promotion during snapshot capture. The future candle's OHLC, volume, and minute-coverage getters must not execute.

Regression: `frontend/tests/hourly-fvg-unknown-coverage-promotion-mutation.test.ts`. The fixture is synthetic and intentionally uses an unverified volume source. A passing test proves only the specified integrity behavior; it does **not** authenticate the provider, minute coverage, broker quotes, trading costs, or strategy profitability. Keep paper-only, draft and undeployed pending independently sourced evidence and exact-head CI.
