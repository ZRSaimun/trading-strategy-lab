# Censor-aware moving-block cost sensitivity (Loop 2)

`backend/app/offline_sweep_censor_aware_blocks.py` is a **disconnected, read-only**, deterministic sensitivity audit. It addresses a limitation of `offline_sweep_block_resampling.py`: removing unknown exits before sampling compresses the observed-trade sequence, so observations separated by censored positions become artificial neighbors. This complementary audit samples contiguous blocks from **all entered positions**, retaining unknown exits in their original locations and never assigning them a return.

```python
from datetime import datetime
from decimal import Decimal
from app.offline_sweep_censor_aware_blocks import EnteredTrade, audit_censor_aware_blocks
report = audit_censor_aware_blocks([
    EnteredTrade(datetime(2025, 1, 1), "development", Decimal("1"), Decimal("100"), Decimal("2")),
    EnteredTrade(datetime(2025, 1, 1, 0, 15), "development", None, Decimal("100"), Decimal("2")),
], block_length=2, resamples=500, seed=20261028)
```

The input is a globally chronological, source-local, **unauthenticated** sequence of entered positions with either a known gross R or a `None` unknown/censored exit. The sample is split by the already-declared `development` and `exploratory_later` labels; each cohort has a separate seeded RNG. Fixed-length moving blocks draw original entered-position indices, including censored positions. A resample's **observed-only** mean is calculated from known exits only. Resamples with no known exits are explicitly counted, not silently treated as zero. Descriptive nearest-rank 2.5%/97.5% bands show both the sampled censored fraction and observed-only net R, using illustrative extra 0/5/10/20-bps round-trip cost `entry * bps / (10000 * risk)` for observed trades only.

**Not inferential:** Unknown exits may be missing-not-at-random; conditioning on observed exits can bias both mean and sampled bands. This audit does not recover full-entered expectancy, establish valid confidence-interval coverage, prove independence, authenticate the source clock, reconstruct unentered signals, check fills, or validate execution spread, slippage, CFD financing or profitability. Blocks follow consecutive *entered positions*, not elapsed time or market bars. Descriptive bands cannot select trading strategies, and the exploratory-later cohort is not an independently protected holdout.

Bounded to 10,000 declared entered positions, 1,000 resamples and 2 million sampled entered-position operations **per cohort**. Invalid timestamps, geometry, types, controls and nonfinite Decimal values fail closed. No raw source timestamps or individual prices are emitted. Treat reports derived from licensed data as private.

From `backend`, run `PYTHONPATH=. pytest -q tests/test_offline_sweep_censor_aware_blocks.py`. This module is not imported by the API, production strategy, paper ledger or broker code; no order permissions. Release remains blocked until exact-head backend/frontend/PostgreSQL/Docker/cloud CI and independently verified backup restoration, rollback, hosting ownership and health checks.
