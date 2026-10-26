"""Offline leave-one-week-out fragility of a frozen, capacity-admitted M1 holdout.

Descriptive only. No post-outcome week filtering, live broker orders, verified
capital feasibility, independent preregistration or claims of profitability.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, localcontext
import heapq

from app.frozen_bracket_population import audit_frozen_bracket_population
from app.frozen_chronological_holdout import _decimal
from app.frozen_holdout_capacity_slots import audit_frozen_holdout_capacity_slots

_COSTS = (0, 5, 10, 20)
_MAX_WEEKS = 520


def _week(at):
    return datetime.fromtimestamp(at, timezone.utc).isocalendar()[:2]


def _withheld(upstream, reason):
    return dict(
        protocol="frozen-m1-capacity-week-fragility-v1",
        status="WITHHELD_INCOMPLETE_OR_INSUFFICIENT",
        reason=reason,
        manifest_sha256=upstream.get("manifest_sha256"),
        eligible_signals=upstream["eligible_signals"],
        declared_excluded_signals=upstream["declared_excluded_signals"],
        training_signals=upstream["training_signals"],
        holdout_signals=upstream["holdout_signals"],
        policy=upstream["policy"],
        admission_counts=upstream["admission_counts"],
        cost_scenarios=[],
        independent_preregistration_verified=False,
        source_authenticated=False,
        untouched_holdout_verified=False,
        capital_feasible_returns_verified=False,
        executable_broker_fills=False,
        verified_profitability=False,
        may_execute_order=False,
    )


def audit_frozen_capacity_week_fragility(
    manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes,
    *, max_positions=1, per_position_risk_bps=100, total_risk_budget_bps=200,
):
    """Evaluate every possible holdout admission-week deletion without selection.

    Reconstruct admissions independently using the same conservative full-horizon
    FIFO policy. Only admitted paths contribute to the hypothetical admitted
    return; rejected paths remain accounted for by the upstream full census.
    All week deletions must leave >=30 admissions and >=12 active ISO UTC weeks.
    """
    upstream = audit_frozen_holdout_capacity_slots(
        manifest, paths, expected_manifest_sha256, cutoff_utc_minute,
        embargo_minutes, max_positions=max_positions,
        per_position_risk_bps=per_position_risk_bps,
        total_risk_budget_bps=total_risk_budget_bps, sample_limit=0,
    )
    if upstream["status"] != "DESCRIPTIVE_FIXED_SLOT_SCENARIOS_ONLY":
        return _withheld(upstream, "Upstream full-population capacity returns withheld")

    audited = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcomes = audited["outcome_audit"]
    if (audited["manifest_sha256"] != upstream["manifest_sha256"]
            or audited["eligible_signals"] != upstream["eligible_signals"]
            or audited["declared_excluded_signals"] != 0
            or outcomes["status"] != "DESCRIPTIVE_BOUNDS_ONLY"
            or outcomes["counts"]["CENSORED"] != 0):
        raise ValueError("Inconsistent complete frozen capacity population")
    by_id = {row["path_id"]: row for row in outcomes["paths"]}
    if len(by_id) != len(manifest["eligible_signals"]):
        raise ValueError("Changed outcome path population")

    # Reconstruct without inspecting outcomes, price movement or early exits.
    horizon = manifest["source"]["horizon_minutes"] * 60
    slots = min(max_positions, total_risk_budget_bps // per_position_risk_bps)
    active = []
    admitted = ([], [])
    skipped = [0, 0]
    peak = 0
    for row in sorted(manifest["eligible_signals"], key=lambda r: (r["signal_at"], r["path_id"])):
        start = row["signal_at"] + 60
        while active and active[0][0] <= start:
            heapq.heappop(active)
        cohort = int(row["signal_at"] >= cutoff_utc_minute)
        if len(active) < slots:
            heapq.heappush(active, (start + horizon, row["path_id"]))
            admitted[cohort].append(row)
            peak = max(peak, len(active))
        else:
            skipped[cohort] += 1

    counts = upstream["admission_counts"]
    if (len(admitted[0]) != counts["training_admitted"]
            or len(admitted[1]) != counts["holdout_admitted"]
            or skipped != [counts["training_unadmitted"], counts["holdout_unadmitted"]]
            or peak != counts["maximum_reserved_full_horizon_slots"]):
        raise ValueError("Independent capacity admission census disagrees")
    holdout = admitted[1]
    week_counts = defaultdict(int)
    for row in holdout:
        week_counts[_week(row["signal_at"])] += 1
    if len(week_counts) != counts["holdout_admitted_utc_weeks"]:
        raise ValueError("Changed admitted holdout week population")
    if (len(week_counts) > _MAX_WEEKS or len(week_counts) < 13
            or any(len(holdout) - n < 30 for n in week_counts.values())):
        return _withheld(upstream, "Every deletion must retain >=30 admitted holdout paths and >=12 UTC weeks (max 520 weeks)")

    if len(upstream["cost_scenarios"]) != len(_COSTS):
        raise ValueError("Incomplete upstream capacity cost scenarios")
    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for index, bps in enumerate(_COSTS):
            base = upstream["cost_scenarios"][index]
            if type(base.get("additional_round_trip_bps")) is not int or base["additional_round_trip_bps"] != bps:
                raise ValueError("Changed upstream cost identity")
            week_lo = defaultdict(lambda: Decimal(0))
            week_hi = defaultdict(lambda: Decimal(0))
            for row in holdout:
                path = by_id[row["path_id"]]
                if path["status"] not in ("DETERMINATE", "AMBIGUOUS"):
                    raise ValueError("Unresolved admitted outcome")
                costs = path.get("cost_scenarios")
                if not isinstance(costs, list) or len(costs) != len(_COSTS):
                    raise ValueError("Incomplete admitted outcome cost scenarios")
                cost = costs[index]
                if type(cost.get("additional_round_trip_bps")) is not int or cost["additional_round_trip_bps"] != bps:
                    raise ValueError("Changed per-path cost identity")
                lo, hi = _decimal(cost.get("lower_net_r")), _decimal(cost.get("upper_net_r"))
                if lo > hi:
                    raise ValueError("Inverted outcome bounds")
                week = _week(row["signal_at"])
                week_lo[week] += lo
                week_hi[week] += hi
            if set(week_lo) != set(week_counts) or set(week_hi) != set(week_counts):
                raise ValueError("Changed week outcome population")
            total_lo, total_hi = sum(week_lo.values()), sum(week_hi.values())
            n = Decimal(len(holdout))
            baseline_lo, baseline_hi = total_lo / n, total_hi / n
            if (baseline_lo != _decimal(base.get("holdout_admitted_mean_lower_net_r"))
                    or baseline_hi != _decimal(base.get("holdout_admitted_mean_upper_net_r"))):
                raise ValueError("Capacity return bounds disagree with independently reconstructed outcomes")
            deletions = [
                ((total_lo - week_lo[week]) / Decimal(len(holdout) - week_counts[week]),
                 (total_hi - week_hi[week]) / Decimal(len(holdout) - week_counts[week]))
                for week in sorted(week_counts)
            ]
            if any(lo > hi for lo, hi in deletions):
                raise ValueError("Inverted deletion return bounds")
            reports.append(dict(
                additional_round_trip_bps=bps,
                original_admitted_holdout_mean_lower_net_r=str(baseline_lo),
                original_admitted_holdout_mean_upper_net_r=str(baseline_hi),
                minimum_leave_one_week_out_mean_lower_net_r=str(min(lo for lo, _ in deletions)),
                minimum_leave_one_week_out_mean_upper_net_r=str(min(hi for _, hi in deletions)),
                maximum_leave_one_week_out_mean_lower_net_r=str(max(lo for lo, _ in deletions)),
                maximum_leave_one_week_out_mean_upper_net_r=str(max(hi for _, hi in deletions)),
                deletions_with_positive_lower_bound=sum(lo > 0 for lo, _ in deletions),
                deletions_with_nonpositive_upper_bound=sum(hi <= 0 for _, hi in deletions),
                deletions_with_uncertain_sign=sum(lo <= 0 < hi for lo, hi in deletions),
                every_week_deletion_lower_bound_positive=all(lo > 0 for lo, _ in deletions),
            ))

    return dict(
        protocol="frozen-m1-capacity-week-fragility-v1",
        status="DESCRIPTIVE_CAPACITY_ADMITTED_WEEK_FRAGILITY_ONLY",
        manifest_sha256=audited["manifest_sha256"],
        cutoff_utc_minute=cutoff_utc_minute,
        embargo_minutes=embargo_minutes,
        eligible_signals=upstream["eligible_signals"],
        declared_excluded_signals=0,
        training_signals=upstream["training_signals"],
        holdout_signals=upstream["holdout_signals"],
        policy=upstream["policy"],
        admission_counts=counts,
        admitted_holdout_active_utc_weeks=len(week_counts),
        maximum_week_admitted_signal_count=max(week_counts.values()),
        minimum_remaining_admitted_holdout_signals=min(len(holdout) - n for n in week_counts.values()),
        cost_scenarios=reports,
        independent_preregistration_verified=False,
        source_authenticated=False,
        untouched_holdout_verified=False,
        capital_feasible_returns_verified=False,
        executable_broker_fills=False,
        verified_profitability=False,
        may_execute_order=False,
        warning=("Post-outcome week deletions are descriptive stress cases, never filters "
                 "or evidence to optimize a strategy. Admissions reserve full horizons, "
                 "not hindsight exits. Rejected signals remain in the upstream census. "
                 "Cost bps are illustrative; fixed-slot R is not capital-feasible "
                 "compounded P&L or executable BID/ASK, spread, financing or slippage. "
                 "The supplied manifest digest/cutoff do not prove an independently "
                 "sealed holdout, licensed data, or a profitable trading edge."),
    )
