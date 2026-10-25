# Frozen chronological holdout: fixed-slot capacity census (Loop 2)

`backend/app/frozen_holdout_capacity_slots.py` is a disconnected, offline, **research-only** thought experiment for limited simultaneous hypothetical positions. It extends the existing frozen chronological holdout and full-horizon exposure audits. There is no new API, broker integration, order, import, migration, persistent journal, paid feed or production configuration change.

```python
from app.frozen_holdout_capacity_slots import audit_frozen_holdout_capacity_slots

report = audit_frozen_holdout_capacity_slots(
    manifest, observed_paths, externally_preserved_manifest_sha256,
    cutoff_utc_minute=PREDECLARED_MONDAY_UTC_EPOCH,
    embargo_minutes=1440,
    max_positions=1, per_position_risk_bps=100,
    total_risk_budget_bps=200,
)
```

## Fixed causal admission rule

Freeze the slot/risk policy, eligibility, source digest and cutoff **before** the relevant observations. Process every eligible frozen signal in ascending UTC completed-signal minute and path ID. A candidate's potential entry is the following minute. Reserve one slot and `per_position_risk_bps` of a **fixed starting-capital** hypothetical risk budget for the *entire* declared horizon, even if a stop/target would have hit sooner. Release only at the end of the half-open interval. Admit if both slot count and budget permit; otherwise count and sample the unadmitted candidate as `SLOT_LIMIT` or `RISK_BUDGET`. The rule cannot inspect subsequent returns, future exit times, price action or profitable labels to choose candidates. All losing and ambiguous signals remain in the original opportunity census. The upstream full-population return bounds are retained separately and are **not** the admitted subset's return.

The risk budget is **not** a margin or account equity calculation: historical BID-only OHLC, broker spreads, financing, slippage, execution size, instrument contract multipliers, leverage, cash movements and adverse gap-loss caps are unverified. A 100 bps risk setting simply scales each admitted historical R by 1% of *fixed initial* hypothetical equity; this is not compounding or proof of capital feasibility. No broker-executable order is generated.

Upstream missing paths, censored observations, declared exclusions, inadequate original train/holdout dispersion, source mismatches and cutoff/embargo leakage **withhold** the report. For admitted-subset statistics, each cohort independently needs at least **30 admissions across 12 UTC ISO weeks**; otherwise only complete admission/rejection counts and the original opportunity statistics are reported. Historical intrabar ambiguity is carried as lower/upper bounds, never resolved optimistically. Four additional illustrative round-trip cost scenarios (0/5/10/20 bps) are inherited from the frozen outcome engine, **not** measured broker execution costs.

The external digest and policy are supplied by the caller; no cryptographic timestamp attests that they were truly fixed before observing results. This is retrospective sensitivity research, not a genuine sealed holdout, not an independently validated portfolio backtest and not evidence of profitable predictions. `may_execute_order`, `verified_profitability`, `capital_feasible_returns_verified`, `source_authenticated`, `independent_preregistration_verified`, and `executable_broker_fills` are always false.

```bash
cd backend
PYTHONPATH=. pytest -q tests/test_frozen_holdout_capacity_slots.py
```

**Cross-loop handoff:** Loop 1 must establish archive rights, source clocks, clean unique historical minutes and authenticated executable BID/ASK. Loop 3 must independently preregister candidate population, policy and untouched holdout. Loop 4 must provide independently reconciled demo fills, cash/margin/liability accounting, emergency controls and explicit per-order approval for any later supported live integration. None of those gates is satisfied by this module.
