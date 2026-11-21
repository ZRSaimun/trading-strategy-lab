# Completed-volume deletion during future timestamp scan

The synthetic regression `frontend/tests/hourly-fvg-future-completed-volume-deletion.test.ts` verifies that a future timestamp getter cannot delete the own `volume` property from a previously completed 1H candle and then allow the scanner to read a later unrevealed future timestamp. The scanner must reject the completed-candle schema mutation immediately, without accessing future OHLC, volume, or minute coverage.

The test deliberately starts with `volume: null` and `volumeVerified: false`: deleting an explicit missing-volume declaration must not silently turn it into valid volume evidence. It tests in-process causal input integrity, not source authentication, actual broker quotes, execution, win rate, or profitability. No historical market prices, orders, production data, credentials, or proprietary datasets are involved.
