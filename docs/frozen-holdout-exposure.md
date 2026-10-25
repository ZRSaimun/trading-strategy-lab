# Frozen chronological holdout potential-exposure census (Loop 2)

`backend/app/frozen_holdout_exposure.py` joins the existing complete-population chronological bracket holdout with a conservative potential-concurrency census. It is **offline, read-only, post-outcome descriptive research**; no broker order, paper fill, API route, migration, production write, provider request, or paid data feed is added.

## Invocation

```python
from app.frozen_holdout_exposure import audit_frozen_holdout_exposure

# expected_manifest_sha256 must come from a separately preserved, pre-outcome
# registration to provide any evidence of a genuine freeze. A self-computed
# digest here proves only internal consistency.
report = audit_frozen_holdout_exposure(
    manifest, observed_paths, expected_manifest_sha256,
    cutoff_utc_minute=PREDECLARED_MONDAY_UTC_EPOCH,
    embargo_minutes=1440,
)
```

The function first runs the existing strict `audit_frozen_chronological_holdout` without modifying its gates. Missing paths, censored outcomes, declared exclusions, an overlapping training label window, fewer than 30 signals or 12 active ISO weeks in either cohort **withhold the combined report**. It revalidates the same frozen population and refuses inconsistent membership or source identity.

For **every** eligible frozen signal, a potential position occupies the half-open interval `[signal_at + 60, signal_at + 60 + horizon_minutes*60)`. A position ending exactly when another begins does not overlap. Even when historical stop/target levels would have exited earlier, no future exit time is used to shorten the interval. The audit counts all simultaneous potential signal pairs and the maximum concurrent signals across training and holdout; counts affected signals and weeks in each cohort; includes bounded adjacent examples; and asserts zero cross-cohort exposure under the existing cutoff/embargo gate. It never removes losing, ambiguous, or overlapping signals to improve historical means.

Four **illustrative** 0/5/10/20 additional round-trip basis-point cohort return bounds are passed through from the upstream chronological auditor unchanged. They are **not** overlap-adjusted, capital-feasible, compounded, statistically independent or executable returns. A potential overlap means one-signal-at-a-time trading, margin utilization and actual fills need separate, preregistered portfolio simulation with verified quotes and risk controls. A no-overlap result does not prove independent outcomes or profitability.

Outputs always set `capital_feasible_returns_verified`, `source_authenticated`, `independent_preregistration_verified`, `executable_broker_fills`, `verified_profitability` and `may_execute_order` to false. The digest and cutoff are caller supplied, so the code cannot independently establish that a holdout was untouched, that archive rights exist, or that executable BID/ASK spreads, commissions, financing and slippage are known.

Synthetic-only regression tests:

```bash
cd backend
PYTHONPATH=. pytest -q tests/test_frozen_holdout_exposure.py
```

**Coordination:** Loop 1 must authenticate and reconcile licensed archive observations; Loop 3 must independently preregister development selection, cutoff and population; Loop 4 must provide separately authorized paper/live account-wide risk, executable quote, and explicit per-order owner confirmation. This census is not an execution gate or strategy recommendation.
