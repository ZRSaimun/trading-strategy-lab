# Offline news-spike first-return and opposite-sweep research (Loop 2)

`app.offline_news_spike_reversal.census_news_spike_reversal` is a **disconnected, read-only, descriptive** event study, not a trade recommendation or profitability model. It addresses a specific historical question: when the first five complete minutes after a declared event break only one side of the preceding 15-minute M1 range, how soon does a completed M1 candle **close back inside** that frozen range, and does price later **touch the opposite side**? It does **not** infer the direction of a future Fed release.

## Exact definitions

- Inputs: sorted unique open-time-stamped **UTC** M1 OHLC candles from **one verified source/instrument/quote side** (the code only validates caller declarations), sorted event IDs/times at least 75 minutes apart, `as_of_utc` minute cutoff and bounded `source_id`.
- Pre-event range: highest high and lowest low of the 15 completed candles before event minute. One-sided spike: a strict high above or low below that range in the **first five completed** event candles, but not both. `both` and `none` are excluded from the directional denominator.
- `first_return_minute`: earliest completed candle close **inside or exactly on** the frozen range, at or after the first directional breakout candle. An initial spike whose own candle closes back inside counts as an immediate rejection at minute 1. A close *past* the opposite side without closing inside does **not** count as a return-to-range.
- `first_opposite_sweep_minute`: earliest candle at or after first break whose low is strictly below pre-low after an upward break, or whose high is strictly above pre-high after a downward break. This is a descriptive touch, **not** proof of intra-minute sequencing, a fill, a stop trigger or a reversal trade.
- For each horizon 5/15/30/60 completed minutes, all constituent M1 bars must be present and complete before outcomes are reported. `pending_horizon` means the horizon is not mature **and no already-completed constituent minute is known missing**. `missing_horizon_minutes` means a completed constituent minute is absent, even if the later cumulative horizon has not yet matured. Both statuses produce null outcomes. A missing pre-event or first-five-minute bar quarantines the event; a not-yet-mature first five is `pending_first_five_completion` instead of a data gap.
- Per-horizon counts report `yes`, `no`, `pending`, `missing` for directional events, observed-only fractions and conservative lower/upper fractions over **all eligible directional events**. Bounds are sensitivity limits, not confidence intervals.

## Integrity and limitations

This is intentionally separate from the existing news-spike persistence/attrition reports; no production route, alert, database, broker interface or source archive is modified. Input is validated for explicit UTC minute alignment, completeness, unique ordering, finite positive internally consistent OHLC, closed schemas and nonoverlapping event windows. No missing candles, event surprise, quote side, timestamps, spread, slippage, financing or order fills are reconstructed. An M1 candle's high and low do **not** reveal whether a stop or target would have occurred first. No source authentication, external event timestamp verification, licensing evidence, protected holdout, trade cost scenario, trading P&L or calibrated forecast is supplied by this helper.

**Research gate:** freeze event inventory and hypothesis before evaluating authenticated archived source-local minutes; split development from an untouched chronological holdout; audit news/event timestamp clocks and cost/quote-side evidence. Do not select only visually successful announcements. No automated or real-money orders are authorized.

Synthetic tests: `cd backend && PYTHONPATH=. pytest -q tests/test_offline_news_spike_reversal.py`.

## Known-gap precedence over later pending horizons (28 October 2026)

For a directional event, if a completed M1 bar at minute 10 is absent when the as-of cutoff is minute 20, horizons 15, 30 and 60 are all `missing_horizon_minutes`: the missing minute is already known and contaminates every cumulative path. In contrast, with complete minutes 0–19, horizons 30 and 60 remain `pending_horizon`; minute 20 is not missing until its close at minute 21. This attribution does not fabricate future bars or observed outcomes. The yes/no denominator and conservative unknown-inclusive bounds remain unchanged. The counters describe caller-declared source completeness, not proven vendor outages, session expectations, trade profitability or calibrated news predictions. Five synthetic boundary/direction/determinism regressions cover this behavior.
