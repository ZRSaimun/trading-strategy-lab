# Paired-direction cost falsification (offline, exploratory)

`app.offline_m1_paired_direction_cost_falsification.audit_m1_paired_direction_cost_falsification(reports)` accepts 2–64 original v1 self-hashed M1 research receipts, validating each through the existing archive robustness and source-isolated census before producing any diagnostics. No original candle prices or archives are published.

For each instrument/provider separately, compare three **matched original entry/exit window** return hypotheses: (1) the frozen CRT/ICT signal direction, (2) the exact opposite position sign at the same timestamps, and (3) a deliberately impossible **hindsight per-archive oracle** that chooses whichever of the two signs gives the better mean return after observing *all outcomes in that archive*. The mirror is an algebraic falsification of directional edge, not a separately backtested trade engine. The oracle leaks the future by construction and must never be used as a model, strategy, or paper/live trading signal.

For 0/5/10/20 illustrative flat round-trip basis-point costs, report trade-count-weighted source means, counts of archives whose **mean** is strictly positive after cost, and whether neither direction is positive for any archive-level mean. These are archive-mean diagnostics, **not** per-trade or cross-parameter performance bounds. In particular, the oracle is not an upper bound on all possible dynamically timed strategies. An archive with zero evaluated outcomes makes every source-level directional statistic unknown rather than silently dropping missing data. One nonempty archive is explicitly marked insufficient replication. Archive SHA order is deterministic, not chronological.

All means are reconstructed from original six-decimal rounded self-reports, using Decimal arithmetic. Receipt SHA-256 does not prove vendor authenticity, provenance, licensing, or actual price-side accuracy. The same windows assumption does not model executable BID/ASK, spreads, slippage, financing, market calendars or broker fill behavior. There is no protected holdout, statistical significance claim, verified profitability, or trading authorization.

Run synthetic regression tests from `backend`:

```bash
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_paired_direction_cost_falsification.py
```

This feature is disconnected from all routes, brokers, database writes, schedulers and live notifications.
