# Frozen CRT/ICT cost frontier (offline, exploratory)

`app.offline_m1_cost_frontier.audit_m1_cost_frontier(reports)` accepts 2–64 original v1 self-hashed M1 archive receipts. It first validates the full cohort using the existing archive-robustness and source-isolated census auditors. It additionally rejects reports with values beyond the six-decimal precision of the original `round(..., 6)` engine. It never fetches data, submits orders, modifies production, or publishes the private archives.

For each **instrument/provider** separately, the function calculates the trade-count-weighted gross basis-point threshold at which a hypothetical fixed-sign strategy, a same-window sign mirror, or a **deliberately impossible per-archive hindsight sign oracle** reaches zero mean return. The oracle selects a direction after observing the archive's completed outcomes and is **never** a tradable signal. A break-even cost threshold is **not** an observed spread, expected return, profitable strategy or cost budget offered by a broker.

Because original means were rounded to six decimals, each original archive mean has at most 0.0000005 bps of arithmetic rounding uncertainty. The fixed/mirrored weighted thresholds use this conservative radius; the oracle takes the absolute-value interval for each archive *before* weighting, with a zero floor. Returned decimal-string interval endpoints are rounded **outward** to seven decimals. At illustrative 0, 5, 10 and 20 bps round-trip costs, each hypothesis is classified only as positive, nonpositive or ambiguous **under receipt rounding**. A cost exactly equal to a rounded gross threshold is ambiguous, not positive. Missing/empty archives suppress all cohort thresholds. A single archive is labelled insufficient replication.

This quantifies **arithmetic sensitivity**, not statistical uncertainty, source authenticity, confidence, significance, generalization, independent archive replication or execution feasibility. Archive SHA order is not time order. Results cannot be used for strategy optimization on already exposed historical archives or to select BUY/SELL orders. No protected holdout, actual BID/ASK, verified source-wall timezone, slippage, financing or broker fills are established. Real executable costs may be materially larger and time-varying.

Synthetic-only regression from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_cost_frontier.py
```

This is an isolated research function with no API route, scheduled job, database, notification or broker integration.
