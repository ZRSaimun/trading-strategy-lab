"""Offline additional-cost capacity for complete frozen M1 bracket outcomes.

Descriptive arithmetic only. Not a broker spread estimate, a predictive edge,
a statistical confidence interval, or an executable trading signal.
"""
from decimal import Decimal, InvalidOperation, ROUND_FLOOR, localcontext

from app.frozen_bracket_population import audit_frozen_bracket_population

_COSTS = (0, 5, 10, 20)
_SIX_DP = Decimal("0.000001")


def _decimal(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 160:
        raise ValueError("Missing bounded decimal return")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed decimal return") from exc
    if not result.is_finite():
        raise ValueError("Nonfinite decimal return")
    return result


def _withheld(audit, reason):
    return dict(
        status="WITHHELD_INCOMPLETE_OR_INSUFFICIENT",
        reason=reason,
        eligible_signals=audit["eligible_signals"],
        declared_excluded_signals=audit["declared_excluded_signals"],
        cost_scenarios=[],
        zero_mean_lower_bound_cost_bps_floor_6dp=None,
        zero_mean_upper_bound_cost_bps_floor_6dp=None,
        verified_profitability=False,
        executable_broker_fills=False,
    )


def summarize_frozen_cost_capacity(audit, manifest):
    """Compute descriptive cost-to-zero thresholds without dropping any paths.

    Thresholds are *floored* to six decimal places and are only descriptive
    interpolation under the upstream linear notional-bps cost assumption.
    They are not an estimate of an actual executable bid/ask spread.
    """
    if not isinstance(audit, dict) or not isinstance(manifest, dict):
        raise ValueError("Frozen audit and manifest required")
    outcome = audit.get("outcome_audit")
    if not isinstance(outcome, dict):
        raise ValueError("Missing upstream frozen outcome audit")
    rows = outcome.get("paths")
    counts = outcome.get("counts")
    eligible = manifest.get("eligible_signals")
    if not isinstance(rows, list) or not isinstance(eligible, list) or not isinstance(counts, dict):
        raise ValueError("Malformed upstream frozen population")
    if (audit.get("complete_against_supplied_manifest") is not True
            or type(audit.get("eligible_signals")) is not int
            or audit["eligible_signals"] != len(rows)
            or len(eligible) != len(rows)
            or type(outcome.get("total")) is not int
            or outcome["total"] != len(rows)
            or outcome.get("verified_profitability") is not False
            or outcome.get("executable_broker_fills") is not False
            or any(type(counts.get(k)) is not int or counts[k] < 0
                   for k in ("DETERMINATE", "AMBIGUOUS", "CENSORED"))
            or sum(counts[k] for k in ("DETERMINATE", "AMBIGUOUS", "CENSORED")) != len(rows)):
        raise ValueError("Inconsistent upstream frozen population audit")
    if (type(audit.get("declared_excluded_signals")) is not int
            or audit["declared_excluded_signals"] != 0
            or counts["CENSORED"] != 0
            or outcome.get("status") != "DESCRIPTIVE_BOUNDS_ONLY"
            or len(rows) < 30
            or type(outcome.get("active_utc_weeks")) is not int
            or outcome["active_utc_weeks"] < 12):
        return _withheld(audit, "Excluded, censored or insufficient time-dispersed signals")

    frozen = {row["path_id"]: row for row in eligible}
    if len(frozen) != len(rows) or set(frozen) != {row["path_id"] for row in rows}:
        raise ValueError("Missing or duplicated frozen signal identity")
    scenarios = outcome.get("cost_scenarios")
    if not isinstance(scenarios, list) or len(scenarios) != len(_COSTS):
        raise ValueError("Unexpected upstream cost scenarios")

    with localcontext() as ctx:
        ctx.prec = 80
        gross_lower = Decimal(0)
        gross_upper = Decimal(0)
        sensitivity = Decimal(0)
        totals = [[Decimal(0), Decimal(0)] for _ in _COSTS]
        for row in rows:
            key = row["path_id"]
            if row.get("status") not in ("DETERMINATE", "AMBIGUOUS"):
                raise ValueError("Unresolved frozen outcome")
            lo, hi = _decimal(row.get("lower_gross_r")), _decimal(row.get("upper_gross_r"))
            if lo > hi:
                raise ValueError("Inverted gross outcome bounds")
            gross_lower += lo
            gross_upper += hi
            signal = frozen[key]
            entry = _decimal(signal["entry"])
            stop = _decimal(signal["stop"])
            risk = abs(entry - stop)
            if risk == 0:
                raise ValueError("Zero frozen initial risk")
            sensitivity += abs(entry) / (Decimal(10000) * risk)
            per_path = row.get("cost_scenarios")
            if not isinstance(per_path, list) or len(per_path) != len(_COSTS):
                raise ValueError("Missing per-path cost scenarios")
            for index, bps in enumerate(_COSTS):
                cost = per_path[index]
                if (not isinstance(cost, dict)
                        or type(cost.get("additional_round_trip_bps")) is not int
                        or cost["additional_round_trip_bps"] != bps):
                    raise ValueError("Changed per-path cost identity")
                low, high = _decimal(cost.get("lower_net_r")), _decimal(cost.get("upper_net_r"))
                if low > high:
                    raise ValueError("Inverted net outcome bounds")
                totals[index][0] += low
                totals[index][1] += high

        if sensitivity <= 0:
            raise ValueError("Invalid nonpositive notional cost sensitivity")
        reports = []
        for index, bps in enumerate(_COSTS):
            item = scenarios[index]
            if (not isinstance(item, dict)
                    or type(item.get("additional_round_trip_bps")) is not int
                    or item["additional_round_trip_bps"] != bps):
                raise ValueError("Changed upstream cost identity")
            low, high = totals[index]
            expected_low = gross_lower - sensitivity * bps
            expected_high = gross_upper - sensitivity * bps
            # The upstream path evaluator uses a finite 50-digit Decimal context.
            # Allow only rounding-scale differences, never a meaningful cost drift.
            tolerance = max(Decimal("1e-35"),
                            abs(expected_low) * Decimal("1e-45"),
                            abs(expected_high) * Decimal("1e-45"))
            if abs(low - expected_low) > tolerance or abs(high - expected_high) > tolerance:
                raise ValueError("Inconsistent linear cost arithmetic")
            reports.append(dict(
                additional_round_trip_bps=bps,
                total_lower_net_r=str(low),
                total_upper_net_r=str(high),
                lower_bound_positive=low > 0,
                upper_bound_nonpositive=high <= 0,
                zero_within_bounds=low <= 0 < high,
            ))

        def floor_break_even(gross):
            if gross <= 0:
                return None
            return str((gross / sensitivity).quantize(_SIX_DP, rounding=ROUND_FLOOR))

        positive_lower = [x["additional_round_trip_bps"] for x in reports if x["lower_bound_positive"]]
        nonpositive_upper = [x["additional_round_trip_bps"] for x in reports if x["upper_bound_nonpositive"]]
        return dict(
            status="DESCRIPTIVE_COST_CAPACITY_ONLY",
            eligible_signals=len(rows),
            declared_excluded_signals=0,
            active_utc_weeks=outcome["active_utc_weeks"],
            gross_total_lower_r=str(gross_lower),
            gross_total_upper_r=str(gross_upper),
            additional_notional_cost_r_per_bps=str(sensitivity),
            zero_mean_lower_bound_cost_bps_floor_6dp=floor_break_even(gross_lower),
            zero_mean_upper_bound_cost_bps_floor_6dp=floor_break_even(gross_upper),
            largest_tested_bps_with_positive_lower_bound=max(positive_lower) if positive_lower else None,
            first_tested_bps_with_nonpositive_upper_bound=min(nonpositive_upper) if nonpositive_upper else None,
            cost_scenarios=reports,
            verified_profitability=False,
            executable_broker_fills=False,
            untouched_holdout_verified=False,
            externally_preregistered=False,
            warning=("After-outcome linear notional-cost sensitivity, not executable spread, "
                     "broker commissions, financing, margin, a calibrated uncertainty interval, "
                     "or a profitable strategy. Intrabar ambiguity is preserved. Matching a "
                     "self-supplied digest does not prove preregistration, archive rights, "
                     "complete eligibility, valid UTC timestamps or untouched holdouts."),
        )


def audit_frozen_cost_capacity(manifest, paths, expected_manifest_sha256):
    """Apply strict frozen-population evaluation before cost capacity arithmetic."""
    audit = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    return summarize_frozen_cost_capacity(audit, manifest)
