# Conditional censored-exit return bounds (Loop 2)

`backend/app/offline_sweep_censor_bounds.py` provides a disconnected, read-only, deterministic sensitivity audit of **caller-declared** entered CRT/ICT trades. It complements the moving-block diagnostics: instead of silently dropping unknown exits or assigning them invented outcomes, it calculates the range of **full-entered** average net R *if* every unknown gross exit were within a caller-chosen interval.

```python
from datetime import datetime
from decimal import Decimal
from app.offline_sweep_censor_aware_blocks import EnteredTrade
from app.offline_sweep_censor_bounds import audit_censored_exit_bounds
report = audit_censored_exit_bounds([
    EnteredTrade(datetime(2025, 1, 1), "development", Decimal("1"), Decimal("100"), Decimal("2")),
    EnteredTrade(datetime(2025, 1, 1, 0, 15), "development", None, Decimal("100"), Decimal("2")),
], missing_gross_lower=Decimal("-1"), missing_gross_upper=Decimal("1"))
```

For `n` entered positions, `m` unknown exits, observed gross sum `G`, declared missing gross bounds `[L,U]`, and illustrative additional round-trip bps `b`, the conditional mean net-R interval is `[(G + m*L - b*C)/n, (G + m*U - b*C)/n]`, where `C = sum(entry/(10000*risk))` over **all entered positions**. The unknown gross-R mean required to reach zero net-R is `(b*C-G)/m` when `m>0`. Both are sensitivity identities, **not estimated missing outcomes**. The extra cost assumption charges all entered positions, including those with censored exits, and is not authenticated broker execution data. Scenario bps: 0, 5, 10, 20. Cohorts remain separate; no resampling or strategy selection occurs.

**Critical limitation:** Default `[-1,+1]` missing gross-R bounds are *illustrative*, not an authenticated stop-loss or take-profit guarantee. A gap, stale quote, financing, execution rejection or other market conditions may cause losses below -1R, and profits may exceed +1R. Thus even a positive conditional lower bound is **not** a verified positive expectancy, confidence interval, statistically significant result, or trade recommendation. No missing-exit mechanism is assumed; the bounds are not calibrated to market data. Source-local timestamps are unauthenticated; independent source-to-UTC custody, historical cohort eligibility, protected holdout, executable quote costs and broker entitlement remain outstanding.

Input requires globally increasing naive source-local `datetime`, valid `EnteredTrade` geometry and explicit `Decimal` assumptions. The report emits aggregate cohort counts and stringified decimal scenarios only, not raw prices, timestamps or licensed data. Maximum 10,000 entered positions. This module is not wired into the API, production strategy, broker or paper order simulator. It cannot place trades or activate alerts.

From `backend`: `PYTHONPATH=. pytest -q tests/test_offline_sweep_censor_bounds.py`. No production deployment until all CI and independent backup-restore/rollback/authenticated-health gates are met.
