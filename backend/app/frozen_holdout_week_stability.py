"""Retrospective leave-one-UTC-week-out fragility of a frozen M1 holdout.

This is a descriptive stress test, never a week selector, calibrated interval,
sealed holdout, source authentication, or executable trading instruction.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from app.frozen_bracket_population import audit_frozen_bracket_population
from app.frozen_chronological_holdout import audit_frozen_chronological_holdout

_COSTS = (0, 5, 10, 20)
_MAX_WEEKS = 520


def _number(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        raise ValueError("Bounded exact net-R string required")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed exact net-R bound") from exc
    if not number.is_finite():
        raise ValueError("Nonfinite exact net-R bound")
    return number


def _withheld(base, reason):
    return dict(
        protocol="frozen-m1-holdout-week-stability-v1",
        status="WITHHELD_INCOMPLETE_OR_INSUFFICIENT",
        reason=reason,
        cutoff_utc_minute=base["cutoff_utc_minute"],
        embargo_minutes=base["embargo_minutes"],
        eligible_signals=base["eligible_signals"],
        declared_excluded_signals=base["declared_excluded_signals"],
        holdout_signals=base["holdout_signals"],
        holdout_active_utc_weeks=base["holdout_active_utc_weeks"],
        cost_scenarios=[],
        independent_preregistration_verified=False,
        untouched_holdout_verified=False,
        source_authenticated=False,
        executable_broker_fills=False,
        verified_profitability=False,
        may_execute_order=False,
    )


def audit_frozen_holdout_week_stability(
    manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes
):
    """Stress every active holdout ISO week, never choosing a favorable omission.

    Every possible one-week deletion must retain >=30 holdout signals and >=12
    active weeks; otherwise suppress all returns. All original frozen signals
    remain in the baseline and all omitted-week cases are inspected.
    """
    base = audit_frozen_chronological_holdout(
        manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes
    )
    if base["status"] != "DESCRIPTIVE_CHRONOLOGICAL_COMPARISON_ONLY":
        return _withheld(base, "Upstream chronological holdout withheld: " + base["reason"])

    audit = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcome = audit["outcome_audit"]
    rows = outcome["paths"]
    if (audit["manifest_sha256"] != base["manifest_sha256"]
            or audit["eligible_signals"] != base["eligible_signals"]
            or audit["declared_excluded_signals"] != 0
            or outcome["status"] != "DESCRIPTIVE_BOUNDS_ONLY"
            or outcome["counts"]["CENSORED"] != 0
            or len(rows) != base["eligible_signals"]):
        raise ValueError("Inconsistent full frozen population and chronological holdout")

    frozen = {item["path_id"]: item for item in manifest["eligible_signals"]}
    if len(frozen) != len(rows) or set(frozen) != {row["path_id"] for row in rows}:
        raise ValueError("Changed frozen population membership")
    holdout = [row for row in rows if frozen[row["path_id"]]["signal_at"] >= cutoff_utc_minute]
    if len(holdout) != base["holdout_signals"]:
        raise ValueError("Changed holdout membership")

    week_by_id = {}
    week_counts = defaultdict(int)
    for row in holdout:
        iso = datetime.fromtimestamp(frozen[row["path_id"]]["signal_at"], timezone.utc).isocalendar()
        week = (iso.year, iso.week)
        week_by_id[row["path_id"]] = week
        week_counts[week] += 1
    if len(week_counts) != base["holdout_active_utc_weeks"]:
        raise ValueError("Changed holdout UTC week population")
    if (len(week_counts) > _MAX_WEEKS
            or any(len(holdout) - count < 30 for count in week_counts.values())
            or len(week_counts) - 1 < 12):
        return _withheld(base, "At least one single-week deletion leaves fewer than 30 signals or 12 active weeks, or exceeds 520 weeks")

    upstream = outcome["cost_scenarios"]
    base_costs = base["cost_scenarios"]
    if not isinstance(upstream, list) or not isinstance(base_costs, list) or len(upstream) != 4 or len(base_costs) != 4:
        raise ValueError("Incomplete upstream cost scenarios")

    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for index, bps in enumerate(_COSTS):
            if (type(upstream[index].get("additional_round_trip_bps")) is not int
                    or upstream[index]["additional_round_trip_bps"] != bps
                    or type(base_costs[index].get("additional_round_trip_bps")) is not int
                    or base_costs[index]["additional_round_trip_bps"] != bps):
                raise ValueError("Changed upstream cost scenario identity")
            sums_lo = defaultdict(lambda: Decimal(0))
            sums_hi = defaultdict(lambda: Decimal(0))
            for row in holdout:
                costs = row.get("cost_scenarios")
                if not isinstance(costs, list) or len(costs) != len(_COSTS):
                    raise ValueError("Incomplete per-path cost scenarios")
                item = costs[index]
                if (type(item.get("additional_round_trip_bps")) is not int
                        or item["additional_round_trip_bps"] != bps):
                    raise ValueError("Changed per-path cost identity")
                if row["status"] not in ("DETERMINATE", "AMBIGUOUS"):
                    raise ValueError("Unresolved outcome in complete holdout")
                lo, hi = _number(item.get("lower_net_r")), _number(item.get("upper_net_r"))
                if lo > hi:
                    raise ValueError("Inverted exact path return bounds")
                week = week_by_id[row["path_id"]]
                sums_lo[week] += lo
                sums_hi[week] += hi
            if set(sums_lo) != set(week_counts) or set(sums_hi) != set(week_counts):
                raise ValueError("Missing week outcome population")
            total_lo, total_hi = sum(sums_lo.values()), sum(sums_hi.values())
            original_lo = total_lo / Decimal(len(holdout))
            original_hi = total_hi / Decimal(len(holdout))
            if (original_lo != _number(base_costs[index].get("holdout_mean_lower_net_r"))
                    or original_hi != _number(base_costs[index].get("holdout_mean_upper_net_r"))):
                raise ValueError("Holdout return bounds disagree with chronological audit")

            deletions = [
                ((total_lo - sums_lo[week]) / Decimal(len(holdout) - week_counts[week]),
                 (total_hi - sums_hi[week]) / Decimal(len(holdout) - week_counts[week]))
                for week in sorted(week_counts)
            ]
            if any(lo > hi for lo, hi in deletions):
                raise ValueError("Inverted leave-week-out bounds")
            reports.append(dict(
                additional_round_trip_bps=bps,
                original_holdout_mean_lower_net_r=str(original_lo),
                original_holdout_mean_upper_net_r=str(original_hi),
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
        protocol="frozen-m1-holdout-week-stability-v1",
        status="DESCRIPTIVE_HOLDOUT_WEEK_STABILITY_ONLY",
        manifest_sha256=audit["manifest_sha256"],
        cutoff_utc_minute=cutoff_utc_minute,
        embargo_minutes=embargo_minutes,
        eligible_signals=len(rows),
        declared_excluded_signals=0,
        holdout_signals=len(holdout),
        holdout_active_utc_weeks=len(week_counts),
        minimum_remaining_holdout_signals=min(len(holdout) - n for n in week_counts.values()),
        cost_scenarios=reports,
        independent_preregistration_verified=False,
        untouched_holdout_verified=False,
        source_authenticated=False,
        executable_broker_fills=False,
        verified_profitability=False,
        may_execute_order=False,
        warning=(
            "Post-outcome leave-one-UTC-week-out descriptive stress; omitted weeks "
            "are not proposed trading filters. Lower/upper extrema may come from "
            "different deletions. Caller-supplied cutoffs/digests cannot establish "
            "a sealed holdout or source rights. Hypothetical R is not compounded "
            "equity or an executable quote; costs exclude verified spread, "
            "slippage, commissions and financing. No profitable edge is established."
        ),
    )
