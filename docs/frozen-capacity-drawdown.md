# Frozen capacity-admitted pseudo-settlement drawdown (Loop 2)

`backend/app/frozen_capacity_drawdown.py` is a disconnected, offline, read-only diagnostic of **fixed-horizon pseudo-settlement** drawdown on frozen CRT/ICT bracket opportunities. It introduces no API route, database migration, scheduler, credentials, broker interface, production feature flag or real-money execution.

```python
from app.frozen_capacity_drawdown import audit_frozen_capacity_drawdown
report = audit_frozen_capacity_drawdown(
    frozen_manifest, frozen_paths, externally_preserved_manifest_sha256,
    cutoff_utc_minute=PREDECLARED_MONDAY_UTC_EPOCH,
    embargo_minutes=1440,
    max_positions=1, per_position_risk_bps=100,
    total_risk_budget_bps=200,
)
```

## What it measures

The strict existing bracket-population, chronological-embargo and full-horizon FIFO capacity audits run first. The new module independently reconstructs admissions from **only frozen signal timestamps and policy**, checking the complete admitted/rejected population and maximum simultaneous reservations against upstream counts. No historical early target or stop outcome releases a slot. An admitted hypothetical position's R outcome is booked at the **predeclared full-horizon end**, then ordered by signal time and path ID to break ties. This artificial convention avoids using realized exit times to change admissions, but **does not represent actual chronological fills, cashflows or intrabar equity**.

For every illustrative additional round-trip cost of **0, 5, 10 and 20 basis points**, each training/holdout path retains its conservative lower and upper net-R bounds. The pseudo-equity is a cumulative **sum of R × fixed initial-equity risk fraction**, without compounding. The maximum peak-to-trough drawdown starts from a zero baseline. The optimistic all-upper path gives a *lower bound* on possible maximum drawdown; the pessimistic all-lower path gives an *upper bound*. This follows because every contiguous interval loss is monotone decreasing in each component return. Report both bounds and final pseudo-equity bounds separately for training and holdout. Recompute admitted mean bounds independently and reject mismatches with the capacity auditor.

No individual winning week, trade, or ambiguity is removed to improve returns. Declared exclusions, censored paths, inadequate cohort size/dispersion, wrong manifest hash, cutoff/embargo leakage, duplicate signals, inconsistent costs or changed admissions cause withholding or rejection. Synthetic regression tests verify baseline losses, cost ordering, ambiguous outcomes, rejection accounting, no hindsight capacity release, invariance to input order and fail-closed conditions.

## Explicit limits and coordination

These percentages are **not executable portfolio equity or risk-of-ruin forecasts**. Fixed-horizon booking may differ greatly from actual stop/target exit time; it excludes intrabar mark-to-market, variable contract sizes, margin, financing, currency conversion, slippage, gaps, forced liquidation, correlated portfolio cashflows and broker fills. The manifest SHA is caller-declared, not proof of independent preregistration. Source licensing, historical timestamp reconciliation and executable BID/ASK costs are not verified; no authenticated historical performance or profitable edge is established.

Loop 1 must resolve source rights, clock/DST collisions and executable quote provenance; Loop 3 must freeze policies and protect holdouts independently; Loop 4 must validate broker paper-account statements, cash/margin/FX liabilities and hard risk gates before any account-level simulation. This research utility must not be used to authorize a trade.
