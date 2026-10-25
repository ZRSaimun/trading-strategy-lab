# Frozen holdout UTC-week deletion stability (Loop 2; offline only)

`backend/app/frozen_holdout_week_stability.py` adds a deterministic **post-outcome, descriptive** stress audit to the existing strict chronological M1 bracket comparison. It does **not** propose omitting any actual trading weeks, adjust strategy parameters, forecast returns, submit orders, or grant execution permission.

## Invocation

```python
from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_holdout_week_stability import audit_frozen_holdout_week_stability

# Only an externally preserved pre-outcome digest could help establish a freeze.
# Recomputing the digest here is NOT independent preregistration.
report = audit_frozen_holdout_week_stability(
    manifest, observed_paths, expected_manifest_sha256,
    cutoff_utc_minute=YOUR_PREDECLARED_MONDAY_UTC_EPOCH,
    embargo_minutes=1440,
)
```

The auditor first runs `audit_frozen_chronological_holdout` unchanged, including the strict Monday UTC cutoff, embargo against *potential* training label overlap, one-to-one frozen signal identity, and the fail-closed censored/excluded/insufficient-population gates. It then independently re-evaluates the complete supplied bracket population and reconciles the original holdout mean return bounds against the chronological audit. The same frozen signal population, including losing and ambiguous paths, is retained throughout.

For **every active ISO UTC week in the holdout**, calculate the holdout mean R after removing that one week **only for stress measurement**. All possible deletions are evaluated; no week is selected for a tradable filter. Require each hypothetical deletion to retain at least 30 signals and 12 distinct active weeks. If any deletion would fail, or there are more than 520 active holdout weeks, **withhold all return statistics**. Baseline holdout statistics always include all weeks.

For each illustrative additional round-trip cost of **0, 5, 10, and 20 bps**, return original lower/upper holdout mean net R, minimum and maximum leave-one-week-out lower/upper means, counts of deletions with definitely positive lower bound / nonpositive upper bound / uncertain sign, and whether *every* deletion retains a positive lower bound. Intrabar ambiguous stop/target paths contribute their adverse lower and favorable upper possibilities; never assume an intraminute touch order. The minimum lower and minimum upper may be produced by **different omitted weeks** and are not an executable joint portfolio result.

## Interpretation and limitations

This is **fragility**, not evidence of statistically independent weeks, a confidence interval, an out-of-sample proof, a prospective test, or a license to optimize the week exclusions. A caller-chosen cutoff or self-supplied digest is **not** a sealed holdout or proof that strategy selection preceded results. The algorithm does not authenticate archives, confirm timestamp conventions or market-data rights, validate executable BID/ASK quotes, or model verified slippage, commission, financing, leverage, margin, overlapping positions, or cash compounding. The historical R units are normalized bracket-risk outcomes, not broker P&L.

No provider calls, network requests, writes, database migrations, API routes, frontend changes, broker integration, order submissions, production data modifications, or paid services are added. The output explicitly sets `independent_preregistration_verified`, `untouched_holdout_verified`, `source_authenticated`, `executable_broker_fills`, `verified_profitability`, and `may_execute_order` to false.

Run the synthetic-only tests with:

```bash
cd backend && PYTHONPATH=. pytest -q tests/test_frozen_holdout_week_stability.py
```

**Coordination:** Loop 1 must establish source provenance, timestamp reconciliation, rights and execution-side evidence; Loop 3 must independently preregister the strategy family, eligibility census, and cutoff before outcomes; Loop 4 must enforce paper/live broker risk and human approval. Loop 2 must then publish positive, negative, censored and ambiguous holdout evidence together, rather than treating this synthetic-tested module as a profitable trading system.
