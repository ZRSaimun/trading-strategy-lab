# Disconnected paper group-concentration overlay (Loop 4)

`backend/app/paper_group_concentration_guard.py` extends the merged, read-only account exposure evaluator without modifying its source or existing broker/paper-journal state. It re-runs the account evaluator on the original strict snapshot and then applies **explicitly declared** instrument-to-risk-group mappings. The wrapper never submits paper/demo/live orders, connects to a broker, persists a risk reservation, signs a confirmation, or authorizes execution. All execution flags remain `false` even if every hypothetical check passes.

## Why

An account may be exposed to the same underlying through several symbol aliases (e.g. `XAUUSD` and `GOLD-CFD`). Each alias could be below a per-symbol concentration cap while their **declared** aggregate group exceeds the cap. This evaluator adds (1) a group notional cap and (2) a group share cap calculated against conservatively stressed account equity. Missing or surplus instrument mappings, missing group caps, malformed or excessive limits, unexpected policy keys and secret-like fields are rejected. No unlisted exposure is silently dropped. A breached base risk check, including emergency stop, remains a hold.

## Contract

From `backend`, import `evaluate_grouped_paper_exposure(snapshot, group_policy, now_ms=trusted_server_ms)`. The `snapshot` is the exact input contract documented in `docs/paper-account-exposure-guard.md`. The policy has exactly three keys:

```python
{
    'instrument_groups': {'XAUUSD': 'GOLD', 'GOLD-CFD': 'GOLD'},
    'group_notional_caps_cash': {'GOLD': '5000'},
    'max_group_share_of_stressed_equity': '0.5',
}
```

Instrument mapping keys must exactly match the instruments in the supplied exposure inventory. Group caps must cover exactly the mapped groups. Group notional uses the underlying evaluator's conservative `gross_notional_cash`, so the base module's declared point values, FX conversions and quantities remain critical assumptions. Group share is evaluated against `stressed_equity_cash`; nonpositive stressed equity fails the share check. Results include `declared_group_notional_cash`, `declared_group_notional_within_cap` and `declared_group_stressed_equity_share_within_cap` checks. Passing only means **ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED**, not a safe order.

## Limits / release

Mappings are **not** verified equivalence classes, correlations, broker contract identifiers or a complete position inventory. Omitted positions and unmapped provider aliases may evade grouping. There is no price-feed authentication, margin-account verification, durable circuit breaker, broker stop fill, order approval or transactionally consistent reservation. Do not use this component as a standalone execution gate. Real-money trading requires a supported broker API, separate protected credentials and explicit positive owner approval for each specific order, in addition to all risk and reconciliation checks. The documented Trading 212 public API does not support CFD order execution.

Synthetic regression tests: `cd backend && PYTHONPATH=. pytest -q tests/test_paper_group_concentration_guard.py`. Run complete backend/frontend/CI and check merge-base, release ownership, restorable backup, rollback and production health before any deployment. This change is additive and needs no database migration or production data change.
