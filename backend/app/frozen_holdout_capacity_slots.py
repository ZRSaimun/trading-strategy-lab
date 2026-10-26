"""Offline, deterministic full-horizon paper-slot capacity census for frozen M1 cohorts.

Admissions depend only on frozen signal timestamps and a predeclared fixed
slot/risk policy, never on future stop/target touches or retrospective returns.
This is NOT margin-aware broker execution, portfolio backtesting, or live risk.
"""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import heapq

from app.frozen_bracket_population import audit_frozen_bracket_population
from app.frozen_chronological_holdout import _decimal
from app.frozen_holdout_exposure import audit_frozen_holdout_exposure

_COSTS = (0, 5, 10, 20)
_MAX_CLOCK = 8640000000


def _week(at):
    return datetime.fromtimestamp(at, timezone.utc).isocalendar()[:2]


def _withheld(upstream, reason, policy):
    return dict(protocol="frozen-m1-holdout-capacity-slots-v1",
                status="WITHHELD_UPSTREAM_INCOMPLETE_OR_LEAKAGE",
                reason=reason, manifest_sha256=upstream.get("manifest_sha256"),
                eligible_signals=upstream["eligible_signals"],
                declared_excluded_signals=upstream["declared_excluded_signals"],
                training_signals=upstream["training_signals"],
                holdout_signals=upstream["holdout_signals"],
                policy=policy, admission_counts=None, cost_scenarios=[],
                source_authenticated=False, independent_preregistration_verified=False,
                capital_feasible_returns_verified=False, verified_profitability=False,
                executable_broker_fills=False, may_execute_order=False)


def audit_frozen_holdout_capacity_slots(
    manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes,
    *, max_positions=1, per_position_risk_bps=100, total_risk_budget_bps=200,
    sample_limit=20,
):
    """Deterministic FIFO capacity at next M1 open with conservative full horizon.

    Fixed fraction of initial capital is a hypothetical risk unit, not cash
    actually reserved at a broker. No price or outcome determines admissions.
    Every signal is accounted for, including unadmitted losses and ambiguities.
    """
    for name, value, low, high in (
        ("max_positions", max_positions, 1, 100),
        ("per_position_risk_bps", per_position_risk_bps, 1, 1000),
        ("total_risk_budget_bps", total_risk_budget_bps, 1, 10000),
        ("sample_limit", sample_limit, 0, 50),
    ):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f"Invalid bounded {name}")
    if per_position_risk_bps > total_risk_budget_bps:
        raise ValueError("A single position exceeds the frozen risk budget")
    effective_slots = min(max_positions, total_risk_budget_bps // per_position_risk_bps)
    policy = dict(max_positions=max_positions,
                  per_position_risk_bps=per_position_risk_bps,
                  total_risk_budget_bps=total_risk_budget_bps,
                  effective_full_horizon_slots=effective_slots)

    upstream = audit_frozen_holdout_exposure(
        manifest, paths, expected_manifest_sha256, cutoff_utc_minute,
        embargo_minutes, sample_limit=0,
    )
    if upstream["status"] != "DESCRIPTIVE_POTENTIAL_EXPOSURE_ONLY":
        return _withheld(upstream, "Upstream full-population holdout/exposure withheld", policy)
    audited = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcome = audited["outcome_audit"]
    if (audited["manifest_sha256"] != upstream["manifest_sha256"]
            or audited["eligible_signals"] != upstream["eligible_signals"]
            or audited["declared_excluded_signals"] != 0
            or outcome["status"] != "DESCRIPTIVE_BOUNDS_ONLY"
            or outcome["counts"]["CENSORED"] != 0):
        raise ValueError("Inconsistent complete frozen population")

    frozen = manifest["eligible_signals"]
    results = {r["path_id"]: r for r in outcome["paths"]}
    if len(results) != len(frozen) or {r["path_id"] for r in frozen} != set(results):
        raise ValueError("Changed frozen path population")
    ordered = sorted(frozen, key=lambda r: (r["signal_at"], r["path_id"]))
    horizon = manifest["source"]["horizon_minutes"] * 60
    active = []  # (conservative full-horizon end, path_id); no outcome exits
    admitted = ([], [])
    skipped = ([], [])
    admitted_weeks = (set(), set())
    reasons = {"SLOT_LIMIT": 0, "RISK_BUDGET": 0}
    peak = 0
    examples = []
    for row in ordered:
        start = row["signal_at"] + 60
        end = start + horizon
        if end > _MAX_CLOCK:
            raise ValueError("Potential position horizon exceeds supported clock")
        while active and active[0][0] <= start:
            heapq.heappop(active)
        cohort = int(row["signal_at"] >= cutoff_utc_minute)
        if len(active) < effective_slots:
            heapq.heappush(active, (end, row["path_id"]))
            admitted[cohort].append(row["path_id"])
            admitted_weeks[cohort].add(_week(row["signal_at"]))
            peak = max(peak, len(active))
        else:
            reason = "SLOT_LIMIT" if len(active) >= max_positions else "RISK_BUDGET"
            reasons[reason] += 1
            skipped[cohort].append(row["path_id"])
            if len(examples) < sample_limit:
                examples.append(dict(path_id=row["path_id"], cohort="HOLDOUT" if cohort else "TRAINING",
                                     entry_at=start, reason=reason))

    if (len(admitted[0]) + len(skipped[0]) != upstream["training_signals"]
            or len(admitted[1]) + len(skipped[1]) != upstream["holdout_signals"]
            or sum(map(len, admitted)) + sum(map(len, skipped)) != len(ordered)):
        raise ValueError("Capacity census lost a frozen signal")
    if peak > effective_slots:
        raise ValueError("Capacity accounting exceeded declared limits")

    counts = dict(training_admitted=len(admitted[0]), holdout_admitted=len(admitted[1]),
                  training_unadmitted=len(skipped[0]), holdout_unadmitted=len(skipped[1]),
                  unadmitted_by_reason=reasons,
                  training_admitted_utc_weeks=len(admitted_weeks[0]),
                  holdout_admitted_utc_weeks=len(admitted_weeks[1]),
                  maximum_reserved_full_horizon_slots=peak)
    # Do not publish cohort return statistics from tiny, concentrated admitted
    # subsets. The original population and rejected-signal counts remain visible.
    sufficient = all(len(admitted[i]) >= 30 and len(admitted_weeks[i]) >= 12 for i in (0, 1))
    scenarios = []
    if sufficient:
        with localcontext() as ctx:
            ctx.prec = 80
            for index, bps in enumerate(_COSTS):
                entry = {"additional_round_trip_bps": bps}
                for cohort, label in enumerate(("training", "holdout")):
                    lo = hi = Decimal(0)
                    for path_id in admitted[cohort]:
                        result = results[path_id]
                        if result["status"] not in ("DETERMINATE", "AMBIGUOUS"):
                            raise ValueError("Unresolved path entered admitted cohort")
                        costs = result["cost_scenarios"]
                        if len(costs) != len(_COSTS) or costs[index]["additional_round_trip_bps"] != bps:
                            raise ValueError("Changed per-path cost identity")
                        lower = _decimal(costs[index]["lower_net_r"])
                        upper = _decimal(costs[index]["upper_net_r"])
                        if lower > upper:
                            raise ValueError("Inverted outcome bounds")
                        lo += lower
                        hi += upper
                    entry[f"{label}_admitted_mean_lower_net_r"] = str(lo / len(admitted[cohort]))
                    entry[f"{label}_admitted_mean_upper_net_r"] = str(hi / len(admitted[cohort]))
                    # R * fixed bps risk; not compounding or executable equity.
                    entry[f"{label}_fixed_initial_equity_lower_pct"] = str(lo * per_position_risk_bps / 100)
                    entry[f"{label}_fixed_initial_equity_upper_pct"] = str(hi * per_position_risk_bps / 100)
                scenarios.append(entry)

    return dict(
        protocol="frozen-m1-holdout-capacity-slots-v1",
        status=("DESCRIPTIVE_FIXED_SLOT_SCENARIOS_ONLY" if sufficient else
                "INSUFFICIENT_ADMITTED_COHORT_FOR_RETURN_STATISTICS"),
        manifest_sha256=audited["manifest_sha256"],
        cutoff_utc_minute=cutoff_utc_minute, embargo_minutes=embargo_minutes,
        eligible_signals=len(ordered), declared_excluded_signals=0,
        training_signals=upstream["training_signals"],
        holdout_signals=upstream["holdout_signals"],
        policy=policy, admission_counts=counts,
        unadmitted_samples=examples, sample_limit=sample_limit,
        cost_scenarios=scenarios,
        full_population_opportunity_cost_scenarios=upstream["cost_scenarios"],
        independent_preregistration_verified=False, source_authenticated=False,
        capital_feasible_returns_verified=False, executable_broker_fills=False,
        verified_profitability=False, may_execute_order=False,
        warning=("Retrospective descriptive FIFO fixed-slot thought experiment only. "
                 "Admissions use timestamps and full declared horizons, never future exits or returns. "
                 "Unadmitted losses remain in the signal census, not the admitted return. "
                 "Risk bps are nominal fractions of fixed starting equity, not real margin, "
                 "notional, financing, executable BID/ASK, slippage, liquidation, "
                 "cashflow, compound returns or broker fills. No profitable edge verified."),
    )
