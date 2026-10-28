# Offline news-spike persistence census (research only)

This disconnected standard-library helper answers a narrow **descriptive** question: after a caller-declared news timestamp, did a five-minute break of the preceding 15 completed M1 candles remain outside that range at 5/15/30/60 minutes? It does not predict the direction of a release, prove that news caused a move, or identify an executable trade.

Call `app.offline_news_spike_persistence.census_news_spike_persistence(candles, events, as_of_utc=..., source_id=...)` with sorted, unique, complete, UTC-minute open-time-stamped M1 OHLC dictionaries, declared event IDs and UTC event times. All inputs must come from **one independently verified source/instrument/price side**. This code cannot verify that assertion. It refuses future/uncompleted candles, inconsistent/nonfinite OHLC, duplicate minutes, overlapping event windows and ambiguous UTC offsets. Missing pre-event or first-five-minute candles quarantine an event; gaps anywhere in a horizon return `insufficient_complete_minutes` rather than fabricating bars.

The pre-event range is frozen from `event-15m` through `event-1m`. A strict high above / low below that range during `event` through `event+4m` yields `up`, `down`, `both` or `none`; **both** is not forced into a directional trade. At horizon H, the close of `event+H-1m` is compared with the frozen range, but only after all H post-event minutes have completed. `aligned` is defined only for one-sided initial spikes. It is not a return, fill, win rate, p-value, confidence interval or forecast probability.

## Reproducibility and restrictions

- Event timestamps, announcement surprise, broker/server timezone, source authenticity, session calendars and historical licensing need independent evidence. Declared UTC is not verified UTC provenance.
- There is no spread, slippage, financing, fees, quote side, entry, stop, fill, margin or trade P&L; do not turn `aligned` into profitability.
- Five-minute reaction classification is only known **after** five completed post-event candles. Never use it to justify a pre-announcement order. Later horizons are evaluated strictly after their respective candles complete.
- Avoid selecting only successful event dates, reusing retrospective events as protected holdout, or treating correlated Fed releases as independent observations. Freeze event inventory and hypothesis before evaluation, then use separate forward data and explicit execution-cost scenarios for any future trade research.
- No network, database, API route, live feed, production feature, broker order or file write is performed by the helper. Tests use synthetic data only.

Run `cd backend && PYTHONPATH=. pytest -q tests/test_offline_news_spike_persistence.py`.
