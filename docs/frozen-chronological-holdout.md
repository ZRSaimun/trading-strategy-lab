# Frozen chronological holdout comparison (offline)

`backend/app/frozen_chronological_holdout.py` adds a read-only, deterministic, **retrospective** two-cohort audit for frozen M1 CRT/ICT bracket hypotheses. It uses the existing `audit_frozen_bracket_population` gate, which independently reevaluates every supplied path from the exact frozen manifest and validates source identity, next-open entry, and OHLC outcome integrity.

## Call

```python
from app.frozen_chronological_holdout import audit_frozen_chronological_holdout
result = audit_frozen_chronological_holdout(
    manifest, paths, expected_manifest_sha256,
    cutoff_utc_minute=1789344000,  # illustrative only; verify a Monday 00:00 UTC
    embargo_minutes=1440,
)
```

**Do not choose the cutoff after inspecting returns.** The caller supplies an explicit UTC Monday 00:00 cutoff and an explicit 1–10,080 minute embargo. A locally supplied cutoff or digest is not an independently sealed, preregistered holdout.

All frozen signals before the cutoff belong to training; signals at or after it belong to holdout. The auditor requires every *possible* training label window (next-open entry plus the full frozen horizon, even if an early stop was observed) to finish before the cutoff minus embargo. Any violation **withholds every performance statistic**, rather than selecting a cleaner subset. It similarly withholds all cohort statistics if **any** frozen path is censored, any pre-signal exclusion was declared, either cohort has fewer than 30 signals or fewer than 12 active UTC calendar weeks, or upstream descriptive population statistics are unavailable.

On complete, time-dispersed populations it reports exact-Decimal training and holdout mean lower/upper R bounds for illustrative additional round-trip notional costs of **0, 5, 10 and 20 bps**. The conservative holdout-minus-training difference interval is `[holdout_lower - training_upper, holdout_upper - training_lower]`. Intrabar stop/target ordering remains uncertain and is never silently resolved in favor of a win. All signals remain in their original cohort. The report is order-independent and does not optimize any parameter or trade on the outcome.

## Scope, safety and limitations

This is **not** an independently protected holdout: the same caller can supply a cutoff, a manifest and the results after observing outcomes. There is no sealed release gate, independently timestamped preregistration, archive authenticity or licensing verification, exchange-session validation, independent sample selection, statistical significance or correction for repeated experiments. The per-path bps scenarios are *illustrative*, not broker executable BID/ASK spreads, slippage, financing, commissions, or live CFD margin costs. Cohort mean R is not a compounded equity curve and correlated trades may overlap.

The auditor makes no provider requests, writes no market data, modifies no database, creates no broker interface, and **never** authorizes paper or live orders. `verified_profitability`, `untouched_holdout_verified` and `may_execute_order` remain false. Run `cd backend && python -m pytest -q tests/test_frozen_chronological_holdout.py` for synthetic regression cases.

**Handoff:** Loop 1 should deliver legally entitled source-authenticated UTC M1 observations and exact side/venue receipts; Loop 3 should independently freeze a complete strategy/config/eligibility census, source lineage and a chronological cutover *before* outcomes; Loop 4 must separately verify eligible broker quotes and per-order human approval. Loop 2 should then run this auditor only on a sealed, single-use holdout with realistic CFD execution costs, and publish negative as well as positive findings.
