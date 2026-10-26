"""Offline fixed-horizon settlement drawdown bounds for frozen capacity cohorts.

Not broker equity, actual execution, or an independently authenticated backtest.
"""
from decimal import Decimal, localcontext
import heapq

from app.frozen_bracket_population import audit_frozen_bracket_population
from app.frozen_chronological_holdout import _decimal
from app.frozen_holdout_capacity_slots import audit_frozen_holdout_capacity_slots

_COSTS = (0, 5, 10, 20)


def _maximum_drawdown_with_window(increments):
    """Return (maximum drawdown, peak event, trough event) in settlement order.

    Event 0 is the initial zero baseline; event N is after N booked paths.
    Equal peaks retain the earliest event, and equal maximum drawdowns retain
    the earliest trough. This is an *artificial* fixed-horizon booking sequence,
    never an actual broker fill or exit timeline.
    """
    equity = peak = maximum = Decimal(0)
    peak_event = best_peak_event = trough_event = 0
    for event_index, increment in enumerate(increments, 1):
        equity += increment
        if equity > peak:
            peak = equity
            peak_event = event_index
        drawdown = peak - equity
        if drawdown > maximum:
            maximum = drawdown
            best_peak_event = peak_event
            trough_event = event_index
    return maximum, best_peak_event, trough_event


def _maximum_drawdown(increments):
    """Exact peak-to-trough loss, including a zero initial baseline.

    Every contiguous interval is a possible peak-to-trough candidate. For
    interval-valued returns, replacing every increment with its lower
    (upper) endpoint maximizes (minimizes) the maximum drawdown.
    """
    return _maximum_drawdown_with_window(increments)[0]



def _terminal_drawdown(increments):
    """Loss at final pseudo-booking relative to the highest earlier event.

    Includes event-zero baseline. All-lower (all-upper) returns maximize
    (minimize) this terminal drawdown. Not a broker mark-to-market balance.
    """
    equity = peak = Decimal(0)
    for increment in increments:
        equity += increment
        if equity > peak:
            peak = equity
    return peak - equity


def _first_pseudo_recovery_event(increments, peak_event, trough_event, maximum):
    """First later booking event recovering the selected drawdown peak.

    None means no positive drawdown or no recovery by the final fixed-horizon
    booking. This is not an observed market exit, broker equity recovery, or
    a causal signal for capacity admission.
    """
    if maximum == 0:
        return None
    if not 0 <= peak_event < trough_event <= len(increments):
        raise ValueError("Invalid pseudo-drawdown event window")
    target = sum(increments[:peak_event], Decimal(0))
    equity = sum(increments[:trough_event], Decimal(0))
    for event_index in range(trough_event + 1, len(increments) + 1):
        equity += increments[event_index - 1]
        if equity >= target:
            return event_index
    return None


def _withheld(upstream, reason):
    return dict(
        protocol="frozen-m1-capacity-drawdown-v1",
        status="WITHHELD_INCOMPLETE_OR_INSUFFICIENT",
        reason=reason,
        manifest_sha256=upstream.get("manifest_sha256"),
        eligible_signals=upstream["eligible_signals"],
        declared_excluded_signals=upstream["declared_excluded_signals"],
        admission_counts=upstream["admission_counts"],
        cost_scenarios=[],
        source_authenticated=False, untouched_holdout_verified=False,
        independent_preregistration_verified=False,
        capital_feasible_returns_verified=False, executable_broker_fills=False,
        verified_profitability=False, may_execute_order=False,
    )


def audit_frozen_capacity_drawdown(
    manifest, paths, expected_manifest_sha256, cutoff_utc_minute, embargo_minutes,
    *, max_positions=1, per_position_risk_bps=100, total_risk_budget_bps=200,
):
    """Bound pseudo-settlement drawdown without outcome-driven admissions.

    Every admitted path is booked at its predeclared full-horizon end, not
    at an observed favorable early exit. The ordering is deterministic and
    independent of the outcome; it is *not* a broker equity time series.
    """
    upstream = audit_frozen_holdout_capacity_slots(
        manifest, paths, expected_manifest_sha256, cutoff_utc_minute,
        embargo_minutes, max_positions=max_positions,
        per_position_risk_bps=per_position_risk_bps,
        total_risk_budget_bps=total_risk_budget_bps, sample_limit=0,
    )
    if upstream["status"] != "DESCRIPTIVE_FIXED_SLOT_SCENARIOS_ONLY":
        return _withheld(upstream, "Upstream complete capacity cohort statistics withheld")
    audited = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcome = audited["outcome_audit"]
    if (audited["manifest_sha256"] != upstream["manifest_sha256"]
            or audited["eligible_signals"] != upstream["eligible_signals"]
            or audited["declared_excluded_signals"] != 0
            or outcome["status"] != "DESCRIPTIVE_BOUNDS_ONLY"
            or outcome["counts"]["CENSORED"] != 0):
        raise ValueError("Inconsistent complete frozen outcome population")
    by_id = {r["path_id"]: r for r in outcome["paths"]}
    if len(by_id) != len(manifest["eligible_signals"]) or set(by_id) != {
            r["path_id"] for r in manifest["eligible_signals"]}:
        raise ValueError("Changed frozen path population")

    # Reconstruct FIFO capacity without inspecting prices, returns or exits.
    horizon = manifest["source"]["horizon_minutes"] * 60
    slots = upstream["policy"]["effective_full_horizon_slots"]
    active = []
    admitted = ([], [])
    rejected = [0, 0]
    peak_slots = 0
    for row in sorted(manifest["eligible_signals"],
                      key=lambda r: (r["signal_at"], r["path_id"])):
        entry = row["signal_at"] + 60
        while active and active[0][0] <= entry:
            heapq.heappop(active)
        cohort = int(row["signal_at"] >= cutoff_utc_minute)
        if len(active) >= slots:
            rejected[cohort] += 1
        else:
            end = entry + horizon
            heapq.heappush(active, (end, row["path_id"]))
            admitted[cohort].append((end, row["signal_at"], row["path_id"]))
            peak_slots = max(peak_slots, len(active))
    counts = upstream["admission_counts"]
    if (len(admitted[0]) != counts["training_admitted"]
            or len(admitted[1]) != counts["holdout_admitted"]
            or rejected != [counts["training_unadmitted"], counts["holdout_unadmitted"]]
            or peak_slots != counts["maximum_reserved_full_horizon_slots"]):
        raise ValueError("Independent admission census disagrees")
    if len(upstream["cost_scenarios"]) != len(_COSTS):
        raise ValueError("Incomplete upstream cost population")

    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for index, bps in enumerate(_COSTS):
            original = upstream["cost_scenarios"][index]
            if type(original.get("additional_round_trip_bps")) is not int or original["additional_round_trip_bps"] != bps:
                raise ValueError("Changed upstream cost identity")
            report = dict(additional_round_trip_bps=bps)
            for cohort, label in enumerate(("training", "holdout")):
                lo, hi = [], []
                for _, _, path_id in sorted(admitted[cohort]):
                    path = by_id[path_id]
                    if path["status"] not in ("DETERMINATE", "AMBIGUOUS"):
                        raise ValueError("Unresolved admitted path")
                    costs = path.get("cost_scenarios")
                    if not isinstance(costs, list) or len(costs) != len(_COSTS):
                        raise ValueError("Incomplete per-path cost population")
                    cost = costs[index]
                    if type(cost.get("additional_round_trip_bps")) is not int or cost["additional_round_trip_bps"] != bps:
                        raise ValueError("Changed per-path cost identity")
                    lower = _decimal(cost.get("lower_net_r"))
                    upper = _decimal(cost.get("upper_net_r"))
                    if lower > upper:
                        raise ValueError("Inverted return interval")
                    lo.append(lower)
                    hi.append(upper)
                if (sum(lo) / len(lo) != _decimal(original[f"{label}_admitted_mean_lower_net_r"])
                        or sum(hi) / len(hi) != _decimal(original[f"{label}_admitted_mean_upper_net_r"])):
                    raise ValueError("Capacity return bounds disagree")
                # Drawdown is antitone in every increment. Optimistic upper
                # returns give minimum possible maximum drawdown; pessimistic
                # lower returns give maximum possible maximum drawdown.
                factor = Decimal(per_position_risk_bps) / Decimal(100)
                best_r, best_peak, best_trough = _maximum_drawdown_with_window(hi)
                worst_r, worst_peak, worst_trough = _maximum_drawdown_with_window(lo)
                best, worst = best_r * factor, worst_r * factor
                best_terminal = _terminal_drawdown(hi) * factor
                worst_terminal = _terminal_drawdown(lo) * factor
                if not (Decimal(0) <= best_terminal <= worst_terminal
                        and best_terminal <= best and worst_terminal <= worst):
                    raise ValueError("Inconsistent terminal drawdown envelope")
                best_recovery = _first_pseudo_recovery_event(
                    hi, best_peak, best_trough, best_r)
                worst_recovery = _first_pseudo_recovery_event(
                    lo, worst_peak, worst_trough, worst_r)
                if best > worst:
                    raise ValueError("Inverted drawdown envelope")
                report[f"{label}_pseudo_settlement_minimum_max_drawdown_pct_initial"] = str(best)
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_peak_event"] = best_peak
                report[f"{label}_pseudo_settlement_minimum_max_drawdown_trough_event"] = best_trough
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_pct_initial"] = str(worst)
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_peak_event"] = worst_peak
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_trough_event"] = worst_trough
                report[f"{label}_pseudo_settlement_minimum_max_drawdown_recovery_event"] = best_recovery
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_recovery_event"] = worst_recovery
                report[f"{label}_pseudo_settlement_minimum_terminal_underwater_pct_initial"] = str(best_terminal)
                report[f"{label}_pseudo_settlement_maximum_terminal_underwater_pct_initial"] = str(worst_terminal)
                report[f"{label}_pseudo_settlement_final_lower_pct_initial"] = str(sum(lo) * factor)
                report[f"{label}_pseudo_settlement_final_upper_pct_initial"] = str(sum(hi) * factor)
            reports.append(report)

    return dict(
        protocol="frozen-m1-capacity-drawdown-v1",
        status="DESCRIPTIVE_FIXED_HORIZON_DRAWDOWN_ENVELOPE_ONLY",
        manifest_sha256=audited["manifest_sha256"],
        cutoff_utc_minute=cutoff_utc_minute, embargo_minutes=embargo_minutes,
        eligible_signals=upstream["eligible_signals"],
        declared_excluded_signals=0,
        policy=upstream["policy"], admission_counts=counts,
        pseudo_settlement_order="full_horizon_end_then_signal_at_then_path_id",
        cost_scenarios=reports,
        source_authenticated=False, untouched_holdout_verified=False,
        independent_preregistration_verified=False,
        capital_feasible_returns_verified=False, executable_broker_fills=False,
        verified_profitability=False, may_execute_order=False,
        warning=("Retrospective synthetic fixed-horizon booking order, NOT broker equity, "
                 "chronological realized cashflow, actual stop/target exit time, intrabar "
                 "mark-to-market drawdown, financing, margin, spread, fill or compounded P&L. "
                 "Cohort admission never uses future outcomes. Costs are illustrative. "
                 "All source rights, data quality, untouched holdout and profitability remain unverified."),
    )
