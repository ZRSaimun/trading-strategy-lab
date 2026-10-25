"""Strict full-population, retrospective UTC chronological holdout comparison.

A cutoff is supplied by the caller, not inferred or optimized from outcomes.
No claim of independently sealed holdout, source rights, significance or edge.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from app.frozen_bracket_population import audit_frozen_bracket_population

_COSTS = (0, 5, 10, 20)
_MIN_SIGNALS = 30
_MIN_WEEKS = 12


def _decimal(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        raise ValueError("Missing bounded exact return")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed exact return") from exc
    if not number.is_finite():
        raise ValueError("Nonfinite exact return")
    return number


def _week(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).isocalendar()[:2]


def _withheld(audit, reason, cutoff, embargo, counts, weeks):
    return dict(
        protocol="frozen-m1-chronological-holdout-v1",
        status="WITHHELD_INCOMPLETE_OR_LEAKAGE_OR_INSUFFICIENT",
        reason=reason,
        cutoff_utc_minute=cutoff,
        embargo_minutes=embargo,
        eligible_signals=audit["eligible_signals"],
        declared_excluded_signals=audit["declared_excluded_signals"],
        training_signals=counts[0],
        holdout_signals=counts[1],
        training_active_utc_weeks=weeks[0],
        holdout_active_utc_weeks=weeks[1],
        cost_scenarios=[],
        untouched_holdout_verified=False,
        independent_preregistration_verified=False,
        source_authenticated=False,
        executable_broker_fills=False,
        verified_profitability=False,
        may_execute_order=False,
    )


def audit_frozen_chronological_holdout(
    manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes
):
    """Compare frozen outcome bounds across a predeclared Monday UTC cutoff.

    Require all training *potential* label windows to finish before the
    cutoff minus embargo, even if a particular stop was touched earlier.
    Never exclude individual signals to manufacture complete subgroups.
    """
    if (type(cutoff_utc_minute) is not int or not 0 <= cutoff_utc_minute <= 8640000000
            or cutoff_utc_minute % 60):
        raise ValueError("Cutoff must be a bounded UTC minute epoch")
    cut = datetime.fromtimestamp(cutoff_utc_minute, timezone.utc)
    if (cut.weekday(), cut.hour, cut.minute, cut.second) != (0, 0, 0, 0):
        raise ValueError("Cutoff must be Monday 00:00 UTC")
    if type(embargo_minutes) is not int or not 1 <= embargo_minutes <= 10080:
        raise ValueError("Explicit 1..10080 minute embargo required")

    audit = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcome = audit["outcome_audit"]
    rows = outcome["paths"]
    frozen = {row["path_id"]: row for row in manifest["eligible_signals"]}
    if len(frozen) != len(rows) or set(frozen) != {row["path_id"] for row in rows}:
        raise ValueError("Frozen population identity mismatch")

    groups = ([], [])
    weeks = (set(), set())
    training_label_overlap = 0
    boundary = cutoff_utc_minute - embargo_minutes * 60
    for row in rows:
        item = frozen[row["path_id"]]
        signal_at = item["signal_at"]
        group = 0 if signal_at < cutoff_utc_minute else 1
        groups[group].append(row)
        weeks[group].add(_week(signal_at))
        if group == 0:
            # Conservative latest possible completion; never infer early exit
            # from outcomes to decide training eligibility.
            last_possible_close = signal_at + 60 + manifest["source"]["horizon_minutes"] * 60
            if last_possible_close > boundary:
                training_label_overlap += 1

    counts = [len(g) for g in groups]
    week_counts = [len(w) for w in weeks]
    if audit["declared_excluded_signals"]:
        return _withheld(audit, "Declared pre-signal exclusions prevent complete population comparison",
                         cutoff_utc_minute, embargo_minutes, counts, week_counts)
    if outcome["counts"]["CENSORED"]:
        return _withheld(audit, "Censored outcome in full frozen population",
                         cutoff_utc_minute, embargo_minutes, counts, week_counts)
    if training_label_overlap:
        return _withheld(audit, "Training potential label window overlaps cutoff embargo",
                         cutoff_utc_minute, embargo_minutes, counts, week_counts)
    if any(n < _MIN_SIGNALS for n in counts) or any(w < _MIN_WEEKS for w in week_counts):
        return _withheld(audit, "Insufficient independent calendar-week dispersion or signals",
                         cutoff_utc_minute, embargo_minutes, counts, week_counts)
    if outcome["status"] != "DESCRIPTIVE_BOUNDS_ONLY":
        return _withheld(audit, "Upstream full-population outcome statistics unavailable",
                         cutoff_utc_minute, embargo_minutes, counts, week_counts)

    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for index, bps in enumerate(_COSTS):
            upstream = outcome["cost_scenarios"][index]
            if (type(upstream.get("additional_round_trip_bps")) is not int
                    or upstream["additional_round_trip_bps"] != bps):
                raise ValueError("Unexpected upstream cost identity")
            bounds = []
            for group in groups:
                lower, upper = Decimal(0), Decimal(0)
                for row in group:
                    if row["status"] not in ("DETERMINATE", "AMBIGUOUS"):
                        raise ValueError("Unresolved outcome was not withheld")
                    costs = row["cost_scenarios"]
                    if not isinstance(costs, list) or len(costs) != len(_COSTS):
                        raise ValueError("Incomplete per-path cost scenarios")
                    cost = costs[index]
                    if (type(cost.get("additional_round_trip_bps")) is not int
                            or cost["additional_round_trip_bps"] != bps):
                        raise ValueError("Changed per-path cost identity")
                    lo, hi = _decimal(cost.get("lower_net_r")), _decimal(cost.get("upper_net_r"))
                    if lo > hi:
                        raise ValueError("Inverted historical uncertainty bounds")
                    lower += lo
                    upper += hi
                bounds.append((lower / Decimal(len(group)), upper / Decimal(len(group))))
            train, test = bounds
            # Difference interval uses the adverse opposite endpoint of
            # the training interval, never an optimistic paired selection.
            reports.append(dict(
                additional_round_trip_bps=bps,
                training_mean_lower_net_r=str(train[0]),
                training_mean_upper_net_r=str(train[1]),
                holdout_mean_lower_net_r=str(test[0]),
                holdout_mean_upper_net_r=str(test[1]),
                holdout_minus_training_lower_net_r=str(test[0] - train[1]),
                holdout_minus_training_upper_net_r=str(test[1] - train[0]),
                holdout_lower_bound_positive=test[0] > 0,
                holdout_upper_bound_nonpositive=test[1] <= 0,
            ))

    return dict(
        protocol="frozen-m1-chronological-holdout-v1",
        status="DESCRIPTIVE_CHRONOLOGICAL_COMPARISON_ONLY",
        cutoff_utc_minute=cutoff_utc_minute,
        embargo_minutes=embargo_minutes,
        manifest_sha256=audit["manifest_sha256"],
        eligible_signals=len(rows),
        declared_excluded_signals=0,
        training_signals=counts[0],
        holdout_signals=counts[1],
        training_active_utc_weeks=week_counts[0],
        holdout_active_utc_weeks=week_counts[1],
        training_label_overlap=0,
        cost_scenarios=reports,
        untouched_holdout_verified=False,
        independent_preregistration_verified=False,
        source_authenticated=False,
        executable_broker_fills=False,
        verified_profitability=False,
        may_execute_order=False,
        warning=("This is a retrospective descriptive comparison using a caller-supplied cutoff, "
                 "not a proven sealed holdout, independent preregistration, significance test, "
                 "validated feed, executable CFD spread, financing estimate, broker fill, "
                 "or profitable strategy. Intrabar uncertainty and all frozen paths are retained."),
    )
