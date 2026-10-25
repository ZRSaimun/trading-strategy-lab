"""Offline four-calendar-week concentration stress for complete frozen M1 outcomes.

Descriptive, post-outcome fragility only. Never a signal filter, confidence
interval, compounded equity curve, broker fill, or permission to trade.
"""
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext

from app.frozen_bracket_population import audit_frozen_bracket_population

_COSTS = (0, 5, 10, 20)
_WINDOW = 4
_MAX_CALENDAR_WEEKS = 520


def _number(value):
    if not isinstance(value, str) or len(value) > 160:
        raise ValueError("Missing exact net-R bound")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed exact net-R bound") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite net-R bound")
    return result


def _monday(signal_at):
    if type(signal_at) is not int or signal_at < 0 or signal_at > 8640000000:
        raise ValueError("Invalid frozen signal clock")
    day = datetime.fromtimestamp(signal_at, timezone.utc).date()
    return day - timedelta(days=day.weekday())


def _withheld(audit, reason, *, span=None):
    return dict(
        status="WITHHELD_INCOMPLETE_OR_INSUFFICIENT",
        reason=reason,
        eligible_signals=audit["eligible_signals"],
        declared_excluded_signals=audit["declared_excluded_signals"],
        calendar_week_span=span,
        cost_scenarios=[],
        verified_profitability=False,
        executable_broker_fills=False,
    )


def summarize_frozen_four_week_shock(audit, manifest):
    """Measure four consecutive UTC-calendar-week sensitivity, including empty weeks.

    Every frozen eligible path is counted once and grouped by signal week.
    Windows are evaluated after outcomes only, with no selective exclusions.
    """
    if not isinstance(audit, dict) or not isinstance(manifest, dict):
        raise ValueError("Frozen population audit and manifest required")
    outcome = audit.get("outcome_audit")
    if not isinstance(outcome, dict):
        raise ValueError("Missing frozen outcome audit")
    rows = outcome.get("paths")
    counts = outcome.get("counts")
    eligible = manifest.get("eligible_signals")
    if not isinstance(rows, list) or not isinstance(counts, dict) or not isinstance(eligible, list):
        raise ValueError("Malformed frozen outcome population")
    if (audit.get("complete_against_supplied_manifest") is not True
            or audit.get("eligible_signals") != len(rows)
            or len(eligible) != len(rows)
            or type(outcome.get("total")) is not int
            or outcome["total"] != len(rows)
            or outcome.get("verified_profitability") is not False
            or outcome.get("executable_broker_fills") is not False
            or any(type(counts.get(k)) is not int or counts[k] < 0
                   for k in ("DETERMINATE", "AMBIGUOUS", "CENSORED"))
            or sum(counts[k] for k in ("DETERMINATE", "AMBIGUOUS", "CENSORED")) != len(rows)):
        raise ValueError("Inconsistent upstream frozen population audit")

    if (audit.get("declared_excluded_signals") != 0
            or counts["CENSORED"] != 0
            or outcome.get("status") != "DESCRIPTIVE_BOUNDS_ONLY"
            or len(rows) < 30
            or type(outcome.get("active_utc_weeks")) is not int
            or outcome["active_utc_weeks"] < 12):
        return _withheld(audit, "Excluded, censored or insufficient time-dispersed signals")

    weeks_by_id = {item["path_id"]: _monday(item["signal_at"]) for item in eligible}
    if len(weeks_by_id) != len(rows):
        raise ValueError("Duplicate frozen signal identity")
    if set(weeks_by_id) != {row["path_id"] for row in rows}:
        raise ValueError("Missing or duplicated frozen path membership")
    first, last = min(weeks_by_id.values()), max(weeks_by_id.values())
    span = (last - first).days // 7 + 1
    if span < 16 or span > _MAX_CALENDAR_WEEKS:
        return _withheld(audit, "Calendar span outside frozen 16-520 week bound", span=span)
    calendar = [first + timedelta(weeks=i) for i in range(span)]
    week_index = {day: i for i, day in enumerate(calendar)}
    per_week_counts = [0] * span
    for week in weeks_by_id.values():
        per_week_counts[week_index[week]] += 1
    if sum(per_week_counts) != len(rows) or sum(c > 0 for c in per_week_counts) != outcome["active_utc_weeks"]:
        raise ValueError("Inconsistent UTC week population")

    upstream_costs = outcome.get("cost_scenarios")
    if not isinstance(upstream_costs, list) or len(upstream_costs) != len(_COSTS):
        raise ValueError("Unexpected upstream cost scenario population")
    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for cost_index, bps in enumerate(_COSTS):
            if (type(upstream_costs[cost_index].get("additional_round_trip_bps")) is not int
                    or upstream_costs[cost_index]["additional_round_trip_bps"] != bps):
                raise ValueError("Changed frozen cost scenario identity")
            lower = [Decimal(0)] * span
            upper = [Decimal(0)] * span
            for row in rows:
                costs = row.get("cost_scenarios")
                if not isinstance(costs, list) or len(costs) != len(_COSTS):
                    raise ValueError("Missing per-path cost scenarios")
                item = costs[cost_index]
                if (type(item.get("additional_round_trip_bps")) is not int
                        or item["additional_round_trip_bps"] != bps):
                    raise ValueError("Changed per-path cost scenario identity")
                lo, hi = _number(item.get("lower_net_r")), _number(item.get("upper_net_r"))
                if lo > hi:
                    raise ValueError("Inverted exact return bounds")
                i = week_index[weeks_by_id[row["path_id"]]]
                lower[i] += lo
                upper[i] += hi

            lower_windows = [sum(lower[i:i + _WINDOW]) for i in range(span - _WINDOW + 1)]
            upper_windows = [sum(upper[i:i + _WINDOW]) for i in range(span - _WINDOW + 1)]
            total_lo, total_hi = sum(lower), sum(upper)
            # Different extremal windows may drive lower and upper bounds.
            reports.append(dict(
                additional_round_trip_bps=bps,
                total_lower_net_r=str(total_lo),
                total_upper_net_r=str(total_hi),
                worst_four_week_lower_net_r=str(min(lower_windows)),
                worst_four_week_upper_net_r=str(min(upper_windows)),
                best_four_week_lower_net_r=str(max(lower_windows)),
                best_four_week_upper_net_r=str(max(upper_windows)),
                leave_best_four_week_out_lower_total_r=str(total_lo - max(lower_windows)),
                leave_best_four_week_out_upper_total_r=str(total_hi - max(upper_windows)),
            ))

    window_counts = [sum(per_week_counts[i:i + _WINDOW]) for i in range(span - _WINDOW + 1)]
    most_crowded = max(range(len(window_counts)), key=lambda i: (window_counts[i], -i))
    return dict(
        status="DESCRIPTIVE_FOUR_WEEK_SHOCK_ONLY",
        eligible_signals=len(rows),
        declared_excluded_signals=0,
        active_utc_weeks=outcome["active_utc_weeks"],
        calendar_week_span=span,
        zero_signal_calendar_weeks=span - outcome["active_utc_weeks"],
        rolling_window_calendar_weeks=_WINDOW,
        most_populated_window_start_utc=calendar[most_crowded].isoformat(),
        most_populated_window_signals=window_counts[most_crowded],
        cost_scenarios=reports,
        verified_profitability=False,
        executable_broker_fills=False,
        untouched_holdout_verified=False,
        externally_preregistered=False,
        warning=("After-outcome descriptive four-week stress, not a confidence interval, "
                 "tradable week filter, or independent holdout. Includes zero-signal weeks. "
                 "Self-supplied hashes cannot prove prior registration, full archive coverage, "
                 "source rights, executable spreads, slippage, financing, or broker fills."),
    )


def audit_frozen_four_week_shock(manifest, paths, expected_manifest_sha256):
    """Use the strict upstream full-population gate before any stress arithmetic."""
    audit = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    return summarize_frozen_four_week_shock(audit, manifest)
