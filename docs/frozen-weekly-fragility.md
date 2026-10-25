# Frozen M1 weekly return fragility (Loop 2; offline only)

`backend/app/frozen_weekly_fragility.py` is a **post-outcome, descriptive** companion to the frozen M1 bracket population and downside-path auditors. It does not select trades, generate signals, connect to a broker, certify profitability, write data, or operate a live service.

## Usage

```python
from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_weekly_fragility import audit_frozen_weekly_fragility

# Preserve a fingerprint independently *before* outcomes, then pass that
# externally preserved digest. Recomputing it here is not preregistration.
report = audit_frozen_weekly_fragility(frozen_manifest, observed_paths, external_digest)
```

The upstream auditor first validates the exact frozen manifest, source identity, one-to-one eligible signal membership, predeclared bracket parameters and complete outcome windows. A matching supplied SHA-256 alone does not prove a genuine pre-outcome freeze. All outcomes remain present, including losses and both possible intrabar bracket paths. Censored outcomes, declared exclusions, fewer than 30 eligible paths or fewer than 12 distinct active ISO UTC weeks **withhold all weekly returns**. More than 520 active weeks also withhold, keeping output bounded.

## Fixed analyses, no tuning

For each additional illustrative round-trip notional-price cost of **0, 5, 10 and 20 bps**, the report aggregates lower and upper *net R* bounds by the UTC ISO week of the original signal, not by a future exit. It reports:

- Total lower/upper net R and counts of weeks definitely positive, definitely negative, or ambiguous across intrabar outcomes.
- Worst single-week lower and upper net R (separately); these are different descriptive paths, not a joint bound on an executable equity curve.
- The least favorable total when one week is omitted, calculated separately for the lower and upper return paths by removing that path's most favorable week. **This is an after-outcome fragility diagnostic, not a proposed trading exclusion rule.**
- The five weeks with the most signals (counts only), plus minimum and maximum signals per active week.

`R` is an additive normalized stop-risk unit. These totals cannot be interpreted as compounded cash equity or an independently executable portfolio, especially where hypothetical positions overlap. The fixed costs are illustrative **additional** costs and do not establish actual spread, slippage, commissions, swaps, financing, gaps or broker availability. Bid-only archives cannot validate executable fills.

No p-values, confidence intervals, selection-adjusted significance or claims of predictive power are produced. A strategy selected after examining the same history is not an untouched holdout. Weekly counts are not independent trials. Compare genuinely frozen hypotheses on chronologically untouched, source-verified datasets with explicit execution costs and separate overlap/financing analysis before any performance interpretation.

## Verification and release gates

`PYTHONPATH=backend python -m pytest -q backend/tests/test_frozen_weekly_fragility.py` runs synthetic-only regressions. Full backend, frontend, PostgreSQL, Docker and cloud CI must pass on the exact PR head before merging. This module has no API route, UI, production data migration, provider key, broker connection, order submission or live-money authority.
