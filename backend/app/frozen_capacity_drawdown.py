"""Offline fixed-horizon settlement drawdown bounds for frozen capacity cohorts.

Not broker equity, actual execution, or an independently authenticated backtest.
"""
from decimal import Decimal, localcontext
import heapq

from app.frozen_bracket_population import audit_frozen_bracket_population
from app.frozen_chronological_holdout import _decimal
from app.frozen_holdout_capacity_slots import audit_frozen_holdout_capacity_slots

_COSTS = (0, 5, 10, 20)
# Illustrative fractions of fixed initial pseudo-equity, not broker risk limits.
_LOSS_BARRIERS_PCT_INITIAL = (10, 20)


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



def _first_pseudo_loss_barrier_event(increments, factor, threshold_pct_initial):
    """First fixed-horizon booking event touching a loss barrier from zero.

    This is a synthetic, uncompounded initial-equity *cumulative* loss,
    not a broker stop, margin call, risk of ruin or actual exit timestamp.
    """
    if factor <= 0 or threshold_pct_initial <= 0:
        raise ValueError("Positive pseudo-risk factor and loss barrier required")
    cumulative = Decimal(0)
    for event, increment in enumerate(increments, 1):
        cumulative += increment * factor
        if cumulative <= -threshold_pct_initial:
            return event
    return None


def _longest_strict_negative_streak(increments):
    """Longest run of consecutive strictly negative pseudo-booked net-R paths.

    Zero is not a loss and breaks the run. These are artificial full-horizon
    bookings, not consecutive broker fills, trading days or calendar minutes.
    """
    longest = current = 0
    for increment in increments:
        if increment < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _strict_sign_count_envelope(lower, upper):
    """Exact bounds on sign counts for independent pseudo-net-R intervals.

    Counts are not probabilities or observed executable win rates. An interval
    spanning zero can contribute to both *possible* positive and negative
    counts; zero is neither a strict win nor a strict loss.
    """
    if len(lower) != len(upper) or any(a > b for a, b in zip(lower, upper)):
        raise ValueError("Inconsistent pseudo-return sign intervals")
    return dict(
        admitted_paths=len(lower),
        guaranteed_strict_positive=sum(a > 0 for a in lower),
        possible_strict_positive=sum(b > 0 for b in upper),
        guaranteed_strict_negative=sum(b < 0 for b in upper),
        possible_strict_negative=sum(a < 0 for a in lower),
        guaranteed_exact_zero=sum(a == b == 0 for a, b in zip(lower, upper)),
        possible_exact_zero=sum(a <= 0 <= b for a, b in zip(lower, upper)),
    )



def _zero_cost_winner_erosion(zero_lower, zero_upper, cost_lower, cost_upper):
    """Paired cost sensitivity for baseline-guaranteed positive pseudo-paths.

    Preserve frozen path identities across scenarios; never use the outcome
    to change admission. These are interval counts, not win probabilities.
    """
    if not (len(zero_lower) == len(zero_upper) == len(cost_lower) == len(cost_upper)):
        raise ValueError("Mismatched paired cost population")
    baseline = certain_lost = possible_lost = certain_survive = 0
    for first_lo, first_hi, later_lo, later_hi in zip(
            zero_lower, zero_upper, cost_lower, cost_upper):
        if (first_lo > first_hi or later_lo > later_hi
                or later_lo > first_lo or later_hi > first_hi):
            raise ValueError("Invalid paired cost interval or nonmonotone erosion")
        if first_lo > 0:
            baseline += 1
            certain_lost += later_hi <= 0
            possible_lost += later_lo <= 0
            certain_survive += later_lo > 0
    if not (0 <= certain_lost <= possible_lost <= baseline
            and possible_lost + certain_survive == baseline):
        raise ValueError("Inconsistent paired winner erosion census")
    return dict(
        evaluated_paths=len(zero_lower),
        zero_cost_guaranteed_strict_positive=baseline,
        guaranteed_no_longer_strict_positive=certain_lost,
        possible_no_longer_strict_positive=possible_lost,
        still_guaranteed_strict_positive=certain_survive,
    )


def _validated_cost_trajectory(costs, *, frozen_entry=None, frozen_stop=None,
                               lower_gross_r=None, upper_gross_r=None):
    """Verify each frozen path's exact illustrative cost erosion.

    Check monotonicity and, when the complete frozen bracket/gross-R identity
    is supplied, recompute each 0/5/10/20-bps net-R endpoint independently.
    This detects monotone but undercharged/overcharged cost trajectories that
    aggregate cohort checks can conceal. The 50-digit Decimal context matches
    the upstream offline bracket evaluator's declared arithmetic convention;
    it does NOT authenticate executable broker costs or source prices.
    """
    if not isinstance(costs, list) or len(costs) != len(_COSTS):
        raise ValueError("Incomplete per-path cost trajectory")
    identity = (frozen_entry, frozen_stop, lower_gross_r, upper_gross_r)
    if any(v is not None for v in identity) and not all(v is not None for v in identity):
        raise ValueError("Incomplete per-path frozen cost identity")
    check_identity = all(v is not None for v in identity)
    if check_identity:
        entry, stop = _decimal(frozen_entry), _decimal(frozen_stop)
        risk = abs(entry - stop)
        if entry == 0 or risk == 0:
            raise ValueError("Invalid frozen bracket cost denominator")
        gross_lower, gross_upper = _decimal(lower_gross_r), _decimal(upper_gross_r)
        if gross_lower > gross_upper:
            raise ValueError("Inverted frozen gross-R interval")
    bounds = []
    with localcontext() as ctx:
        ctx.prec = 50
        for index, bps in enumerate(_COSTS):
            scenario = costs[index]
            if (not isinstance(scenario, dict)
                    or type(scenario.get("additional_round_trip_bps")) is not int
                    or scenario["additional_round_trip_bps"] != bps):
                raise ValueError("Changed per-path cost trajectory identity")
            lower = _decimal(scenario.get("lower_net_r"))
            upper = _decimal(scenario.get("upper_net_r"))
            if lower > upper:
                raise ValueError("Inverted per-path cost trajectory interval")
            if bounds and (lower > bounds[-1][0] or upper > bounds[-1][1]):
                raise ValueError("Nonmonotone individual path cost trajectory")
            if check_identity:
                # Same fixed, declared notional-price cost model as the
                # independent bracket evaluator. Never substitute spread,
                # slippage, financing, or an executable BID/ASK quotation.
                cost = abs(entry) * Decimal(bps) / Decimal(10000) / risk
                if lower != gross_lower - cost or upper != gross_upper - cost:
                    raise ValueError("Incorrect per-path frozen cost erosion")
            bounds.append((lower, upper))
    return tuple(bounds)

def _worst_quartile_mean_envelope(lower, upper):
    """Exact bottom-quarter mean bounds for independently bounded net-R paths.

    Use ceil(N/4) observations, fixed before examining any outcome. Sorting
    outcomes here only computes a retrospective downside statistic: it never
    selects signals, admits positions, or alters the frozen holdout. This is
    not a probability, confidence interval, expected shortfall estimate or
    broker loss measure.
    """
    if (not lower or len(lower) != len(upper)
            or any(a > b for a, b in zip(lower, upper))):
        raise ValueError("Invalid worst-quartile return intervals")
    count = (len(lower) + 3) // 4
    pessimistic = sum(sorted(lower)[:count], Decimal(0)) / count
    optimistic = sum(sorted(upper)[:count], Decimal(0)) / count
    if pessimistic > optimistic:
        raise ValueError("Inverted worst-quartile return envelope")
    return dict(
        admitted_paths=len(lower),
        worst_quartile_paths=count,
        minimum_worst_quartile_mean_net_r=str(pessimistic),
        maximum_worst_quartile_mean_net_r=str(optimistic),
    )


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

    # Validate every eligible path (including capacity-rejected opportunities)
    # before reporting any cohort. Aggregate cost monotonicity alone could hide
    # one path whose optimistic/pessimistic return *improves* at higher costs.
    frozen_by_id = {row["path_id"]: row for row in manifest["eligible_signals"]}
    cost_trajectories = {
        path_id: _validated_cost_trajectory(
            path.get("cost_scenarios"),
            frozen_entry=frozen_by_id[path_id]["entry"],
            frozen_stop=frozen_by_id[path_id]["stop"],
            lower_gross_r=path.get("lower_gross_r"),
            upper_gross_r=path.get("upper_gross_r"),
        )
        for path_id, path in by_id.items()
    }

    # Reconstruct FIFO capacity without inspecting prices, returns or exits.
    horizon = manifest["source"]["horizon_minutes"] * 60
    slots = upstream["policy"]["effective_full_horizon_slots"]
    active = []
    admitted = ([], [])
    unadmitted = ([], [])
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
            unadmitted[cohort].append((entry + horizon, row["signal_at"], row["path_id"]))
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
    admitted_ids = {row[2] for cohort in admitted for row in cohort}
    unadmitted_ids = {row[2] for cohort in unadmitted for row in cohort}
    if (admitted_ids & unadmitted_ids or admitted_ids | unadmitted_ids != set(by_id)
            or any(len(unadmitted[i]) != rejected[i] for i in (0, 1))):
        raise ValueError("Incomplete or overlapping capacity population partition")

    def _bounds_for_population(population, cost_index, expected_bps):
        """Read every frozen path, including capacity-rejected outcomes, without filtering."""
        lower_values, upper_values = [], []
        for _, _, path_id in sorted(population):
            path = by_id[path_id]
            if path["status"] not in ("DETERMINATE", "AMBIGUOUS"):
                raise ValueError("Unresolved frozen path")
            if _COSTS[cost_index] != expected_bps:
                raise ValueError("Changed per-path cost identity")
            lower, upper = cost_trajectories[path_id][cost_index]
            lower_values.append(lower)
            upper_values.append(upper)
        return lower_values, upper_values

    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for index, bps in enumerate(_COSTS):
            original = upstream["cost_scenarios"][index]
            if type(original.get("additional_round_trip_bps")) is not int or original["additional_round_trip_bps"] != bps:
                raise ValueError("Changed upstream cost identity")
            report = dict(additional_round_trip_bps=bps)
            for cohort, label in enumerate(("training", "holdout")):
                lo, hi = _bounds_for_population(admitted[cohort], index, bps)
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
                report[f"{label}_pseudo_settlement_minimum_max_drawdown_peak_event"] = best_peak
                report[f"{label}_pseudo_settlement_minimum_max_drawdown_trough_event"] = best_trough
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_pct_initial"] = str(worst)
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_peak_event"] = worst_peak
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_trough_event"] = worst_trough
                report[f"{label}_pseudo_settlement_minimum_max_drawdown_recovery_event"] = best_recovery
                report[f"{label}_pseudo_settlement_maximum_max_drawdown_recovery_event"] = worst_recovery
                report[f"{label}_pseudo_settlement_minimum_terminal_underwater_pct_initial"] = str(best_terminal)
                report[f"{label}_pseudo_settlement_maximum_terminal_underwater_pct_initial"] = str(worst_terminal)
                # A cumulative lower endpoint touching the barrier means
                # at least one interval-compatible pseudo-path can touch it.
                # An upper endpoint touching it means every interval-compatible
                # pseudo-path has touched it by that event. Neither statement
                # is a probability, a risk-of-ruin forecast or broker equity.
                barriers = []
                for threshold in _LOSS_BARRIERS_PCT_INITIAL:
                    possible = _first_pseudo_loss_barrier_event(
                        lo, factor, Decimal(threshold))
                    unavoidable = _first_pseudo_loss_barrier_event(
                        hi, factor, Decimal(threshold))
                    if (unavoidable is not None and
                            (possible is None or possible > unavoidable)):
                        raise ValueError("Inconsistent pseudo-loss barrier envelope")
                    barriers.append(dict(
                        threshold_pct_initial=threshold,
                        first_possible_event=possible,
                        first_unavoidable_event=unavoidable,
                        envelope_status=(
                            "UNAVOIDABLE_WITHIN_INTERVAL_ENVELOPE"
                            if unavoidable is not None else
                            "POSSIBLE_WITHIN_INTERVAL_ENVELOPE"
                            if possible is not None else
                            "NOT_REACHED_WITHIN_INTERVAL_ENVELOPE"
                        ),
                    ))
                report[f"{label}_pseudo_settlement_loss_barriers"] = barriers
                # Every endpoint can be chosen independently within its R
                # interval. The all-upper path minimizes the longest strict
                # loss streak; the all-lower path maximizes it. No outcome
                # selection or profitable-trade filtering is permitted.
                min_streak = _longest_strict_negative_streak(hi)
                max_streak = _longest_strict_negative_streak(lo)
                if min_streak > max_streak:
                    raise ValueError("Inconsistent negative streak envelope")
                report[f"{label}_pseudo_settlement_minimum_longest_strict_negative_path_streak"] = min_streak
                report[f"{label}_pseudo_settlement_maximum_longest_strict_negative_path_streak"] = max_streak
                report[f"{label}_pseudo_settlement_strict_sign_census"] = (
                    _strict_sign_count_envelope(lo, hi))
                zero_lo, zero_hi = _bounds_for_population(admitted[cohort], 0, 0)
                report[f"{label}_pseudo_settlement_admitted_zero_cost_winner_erosion"] = (
                    _zero_cost_winner_erosion(zero_lo, zero_hi, lo, hi))
                report[f"{label}_pseudo_settlement_worst_quartile_net_r"] = (
                    _worst_quartile_mean_envelope(lo, hi))
                # Capacity-rejected signals remain in the frozen opportunity set.
                # Their sign census is descriptive and NEVER changes admissions.
                skipped_lo, skipped_hi = _bounds_for_population(
                    unadmitted[cohort], index, bps)
                skipped_signs = _strict_sign_count_envelope(skipped_lo, skipped_hi)
                skipped_signs["unadmitted_paths"] = skipped_signs.pop("admitted_paths")
                if skipped_signs["unadmitted_paths"] != counts[f"{label}_unadmitted"]:
                    raise ValueError("Capacity-rejected outcome census disagrees")
                report[f"{label}_pseudo_settlement_unadmitted_strict_sign_census"] = skipped_signs
                skipped_zero_lo, skipped_zero_hi = _bounds_for_population(
                    unadmitted[cohort], 0, 0)
                report[f"{label}_pseudo_settlement_unadmitted_zero_cost_winner_erosion"] = (
                    _zero_cost_winner_erosion(
                        skipped_zero_lo, skipped_zero_hi, skipped_lo, skipped_hi))
                report[f"{label}_pseudo_settlement_final_lower_pct_initial"] = str(sum(lo) * factor)
                report[f"{label}_pseudo_settlement_final_upper_pct_initial"] = str(sum(hi) * factor)
            # Increasing *additional* round-trip costs cannot create strict
            # pseudo-winners or eliminate strict pseudo-losers. Fail closed
            # if an upstream per-path cost scenario violates this ordering.
            if reports:
                previous = reports[-1]
                for label in ("training", "holdout"):
                    tail_key = f"{label}_pseudo_settlement_worst_quartile_net_r"
                    for bound in ("minimum_worst_quartile_mean_net_r",
                                  "maximum_worst_quartile_mean_net_r"):
                        if (_decimal(report[tail_key][bound])
                                > _decimal(previous[tail_key][bound])):
                            raise ValueError("Nonmonotone downside tail cost envelope")
                    for population in ("admitted", "unadmitted"):
                        erosion_key = f"{label}_pseudo_settlement_{population}_zero_cost_winner_erosion"
                        old_erosion, new_erosion = previous[erosion_key], report[erosion_key]
                        if (new_erosion["zero_cost_guaranteed_strict_positive"]
                                != old_erosion["zero_cost_guaranteed_strict_positive"]
                                or new_erosion["guaranteed_no_longer_strict_positive"]
                                < old_erosion["guaranteed_no_longer_strict_positive"]
                                or new_erosion["possible_no_longer_strict_positive"]
                                < old_erosion["possible_no_longer_strict_positive"]
                                or new_erosion["still_guaranteed_strict_positive"]
                                > old_erosion["still_guaranteed_strict_positive"]):
                            raise ValueError("Nonmonotone paired winner erosion")
                    for population in ("strict_sign_census", "unadmitted_strict_sign_census"):
                        key_prefix = f"{label}_pseudo_settlement_{population}"
                        old = previous[key_prefix]
                        new = report[key_prefix]
                        for key in ("guaranteed_strict_positive", "possible_strict_positive"):
                            if new[key] > old[key]:
                                raise ValueError("Nonmonotone pseudo-winner cost census")
                        for key in ("guaranteed_strict_negative", "possible_strict_negative"):
                            if new[key] < old[key]:
                                raise ValueError("Nonmonotone pseudo-loser cost census")
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
