# Offline observed-only moving-block resampling (Loop 2)

This disconnected, read-only standard-library diagnostic reports how **caller-declared observed entered-trade net-R means** vary under deterministic moving-block resampling. It is a descriptive stress check, **not a calibrated confidence interval**, untouched holdout, new archive backtest, authentic BID/ASK, proof of strategy profitability or trading signal.

```python
from datetime import datetime
from decimal import Decimal
from app.offline_sweep_block_resampling import Trade, audit_observed_block_resampling
report = audit_observed_block_resampling([
    Trade(datetime(2025, 1, 1), "development", Decimal("1"), Decimal("100"), Decimal("2")),
    Trade(datetime(2025, 1, 1, 0, 15), "development", None, Decimal("100"), Decimal("2")),
], block_length=2, resamples=500, seed=20261028)
```

`gross_r=None` denotes an **entered position with a censored/unknown exit**; it is never imputed as zero. Confirmed signals with no observable entry are not part of this entered-position sample. Each cohort is resampled independently; trades must be globally chronological and source-local timestamps have no authenticated timezone. Moving blocks span **consecutive observed trade indices**, not M15 bars or elapsed time; removing censored exits can make apparent neighbors nonadjacent in actual market time. Thus even when no exits are censored, 2.5/97.5 nearest-rank bands are algorithmic percentiles, **not valid frequentist coverage claims**. They must never drive strategy/filter selection.

For each observed trade, illustrative additional round-trip 0/5/10/20 bps costs subtract `entry * bps / (10000 * risk)` from the gross-R. Source price and trade geometry are not independently verified; spread, financing, actual slippage and broker fills are unknown. Fixed `seed`, `block_length` and `resamples` are reproducible, not optimized. If no observed trades or fewer observations than block length, the bands are null, not invented. Resource limits: at most 10,000 entered positions, 1,000 resamples and 2 million observed-draw operations per cohort. Reports contain no raw timestamps or individual prices, but still treat licensed source-derived reports as private.

The previously inspected later period is **exploratory**, not an independent protected holdout. This module is optional and disconnected from strategy, database, API, paper broker and production routes. Synthetic verification: `PYTHONPATH=. pytest -q tests/test_offline_sweep_block_resampling.py` from `backend`. Never treat a positive observed-only band as permission to execute an order. Merge/deployment require exact-head backend/frontend/PostgreSQL/Docker/cloud CI and separately verified hosting owner, backup restoration, rollback and health checks.
