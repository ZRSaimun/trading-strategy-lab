"""Disconnected audit of unchanged probabilities in declared forecast decisions.

Exact probability repetition can be a legitimate calibrated baseline; this
operator diagnostic never infers a stuck model, a trading edge or send authority.
"""
from collections import Counter, defaultdict

from .forecast_decision_coverage import audit_forecast_decision_coverage


def _run_lengths(ordered_bases, forecast_probabilities, seconds):
    """Abstentions and nonadjacent expected candles interrupt a probability run."""
    longest = trailing = 0
    longest_bounds = None
    run_start = previous_base = previous_probability = None
    for base in ordered_bases:
        p = forecast_probabilities.get(base)
        if p is None:
            trailing = 0
            previous_probability = None
        elif (previous_base is not None and base - previous_base == seconds
              and previous_probability is not None and p == previous_probability):
            trailing += 1
        else:
            trailing = 1
            run_start = base
        if p is not None:
            if trailing > longest:
                longest = trailing
                longest_bounds = [run_start, base]
            previous_probability = p
        previous_base = base
    return longest, longest_bounds, trailing


def audit_forecast_probability_stagnation(
        snapshot, expected_identity, expected_keys, abstentions, *, as_of,
        min_decisions_per_group=30, min_forecasts_per_group=30,
        warning_consecutive_identical=12, warning_dominance_percent=90):
    """Detect descriptive forecast-output stagnation only after full census.

    Input journal, schedules, timestamps and abstentions remain caller-declared.
    Exact floating-point equality is used: this does not equate nearby values,
    prove model failure, authenticate a feed or grant any trading permission.
    """
    if (type(min_decisions_per_group) is not int or not 30 <= min_decisions_per_group <= 5000
            or type(min_forecasts_per_group) is not int or not 30 <= min_forecasts_per_group <= 5000
            or type(warning_consecutive_identical) is not int
            or not 2 <= warning_consecutive_identical <= 5000
            or type(warning_dominance_percent) is not int
            or not 50 <= warning_dominance_percent <= 100):
        raise ValueError("Invalid probability stagnation audit thresholds")
    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_DECISION_SCHEDULE_AND_FORECASTS_UNVERIFIED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": coverage["expectedCount"],
        "minDecisionsPerGroup": min_decisions_per_group,
        "minForecastsPerGroup": min_forecasts_per_group,
        "warningConsecutiveIdentical": warning_consecutive_identical,
        "warningDominancePercent": warning_dominance_percent,
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithWarning": None,
        "byModelHorizon": [],
        "sourceAuthenticated": False,
        "scheduleIndependentlyVerified": False,
        "forecastOutputsIndependentlyVerified": False,
        "recipientDeliveryVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
    if coverage["status"] == "NO_DECLARED_EXPECTATIONS":
        result["status"] = "NO_DECLARED_EXPECTATIONS"
        return result
    if coverage["status"] != "DECLARED_DECISIONS_MATCH_UNVERIFIED":
        return result

    expected_groups = defaultdict(list)
    for model, horizon, base in expected_keys:
        expected_groups[(model, horizon)].append(base)
    forecast_groups = defaultdict(dict)
    for row in snapshot["forecasts"]:
        forecast_groups[(row["modelVersion"], row["horizon"])][row["baseStart"]] = row["probability"]

    insufficient = warnings = 0
    for (model, horizon), bases in sorted(expected_groups.items()):
        ordered = sorted(bases)
        probabilities = forecast_groups[(model, horizon)]
        if (len(ordered) < min_decisions_per_group
                or len(probabilities) < min_forecasts_per_group):
            insufficient += 1
            continue
        counts = Counter(probabilities.values())
        dominant_probability, dominant_count = sorted(
            counts.items(), key=lambda pair: (-pair[1], pair[0]))[0]
        longest, bounds, trailing = _run_lengths(
            ordered, probabilities, expected_identity["seconds"])
        dominant_fraction = dominant_count / len(probabilities)
        streak_warning = longest >= warning_consecutive_identical
        dominance_warning = dominant_count * 100 >= warning_dominance_percent * len(probabilities)
        warning = streak_warning or dominance_warning
        warnings += int(warning)
        result["byModelHorizon"].append({
            "modelVersion": model,
            "horizonCandles": horizon,
            "expectedDecisionCount": len(ordered),
            "forecastCount": len(probabilities),
            "abstentionCount": len(ordered) - len(probabilities),
            "distinctExactProbabilityCount": len(counts),
            "dominantExactProbability": dominant_probability,
            "dominantExactProbabilityCount": dominant_count,
            "dominantExactProbabilityFraction": dominant_fraction,
            "longestIdenticalProbabilityStreak": longest,
            "longestIdenticalProbabilityStreakBaseStarts": bounds,
            "trailingIdenticalProbabilityStreak": trailing,
            "streakWarning": streak_warning,
            "dominanceWarning": dominance_warning,
            "operatorReviewWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithWarning"] = warnings
    result["status"] = (
        "OPERATOR_REVIEW_REQUIRED" if warnings else
        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
        "DECLARED_PROBABILITY_VARIATION_WITHIN_WARNING_UNVERIFIED")
    return result
