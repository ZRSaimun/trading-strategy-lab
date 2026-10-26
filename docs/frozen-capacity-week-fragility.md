# Frozen capacity-admitted holdout: weekly fragility (Loop 2)

`backend/app/frozen_capacity_week_fragility.py` adds a **disconnected, offline, read-only, descriptive** leave-one-ISO-UTC-week-out stress test of the *capacity-admitted* holdout. It complements (does not replace) the full-population weekly stability audit and the FIFO capacity-slot census. No API, scheduler, database migration, production UI, broker connection, paid data, credential or live order path is introduced.

```python
from app.frozen_capacity_week_fragility import audit_frozen_capacity_week_fragility

report = audit_frozen_capacity_week_fragility(
    frozen_manifest, observed_paths, externally_preserved_manifest_sha256,
    cutoff_utc_minute=PREDECLARED_MONDAY_UTC_EPOCH,
    embargo_minutes=1440,
    max_positions=1, per_position_risk_bps=100,
    total_risk_budget_bps=200,
)
```

## Causal admission and complete population

First run the existing strict full-population bracket, chronological embargo and full-horizon capacity audits. Independently reconstruct admission in ascending frozen signal UTC time and ID. A hypothetical entry occurs at the next M1 open; one slot is reserved until the *entire* predeclared maximum label horizon elapses, even if a historical stop/target would have triggered earlier. This avoids using future exit outcomes to select trades. Fixed slots and nominal risk-bps are **not** actual cash, margin, leverage or broker financing.

Require identical upstream and reconstructed training/holdout admission counts, rejected counts and peak slots. Keep all unadmitted opportunities visible in the upstream census; do not relabel them as winners or erase their losses. Use only admitted holdout paths to compute admitted-subset returns. Validate exact per-path cost scenario identity and recompute the admitted baseline to ensure it matches the upstream capacity audit. Any incomplete/censored outcome, declared exclusion, mismatched SHA-256, cutoff/embargo leakage, changed population, malformed return or conflicting cost identity fails closed.

## Every active week, no post-outcome selection

For each additional round-trip cost of **0, 5, 10 and 20 bps**, independently delete **each** active ISO UTC week of *admitted holdout* observations and recompute the exact-decimal mean lower/upper net-R bounds of the remaining admitted observations. No week is chosen as a proposed trading filter. Report original admitted baseline, minimum and maximum leave-week-out bounds, counts of positive/negative/uncertain sign deletions, maximum week concentration and minimum remaining admitted observations. Lower/upper extrema can arise from different deletions.

Return statistics are withheld unless **every** deletion retains at least **30 admitted paths** across at least **12 active UTC weeks**, and there are no more than 520 active weeks. Withheld reports preserve the full upstream admission/rejection census. The `every_week_deletion_lower_bound_positive` boolean is only a descriptive arithmetic condition on hypothetical OHLC bounds, not evidence of statistically significant, executable or repeatable returns.

## Boundaries and follow-up

This utility cannot authenticate HistData source rights, reconcile colliding timestamps, verify externally frozen eligibility/cutoff, ensure untouched holdout outcomes, measure actual BID/ASK spreads, contract sizing, commissions, slippage, financing, margin calls, correlated drawdowns or broker fills. Nominal R scaled by risk bps is **not capital-feasible compounded portfolio equity**. Synthetic tests are software correctness evidence, not historical strategy validation. No market profitability claim is made.

**Research handoff:** Loop 1 should establish source rights, historical clock/collision quality and executable quote evidence; Loop 3 should independently seal strategy eligibility, cutoff, embargo, cost model and capacity policy before accessing holdout; Loop 4 should reconcile real demo statements, broker-margin, account FX liabilities and hard per-order owner confirmation. Until then, this is a disconnected methodological diagnostic.
