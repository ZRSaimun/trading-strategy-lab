"""Offline, declared-only forecast direction-reversal diagnostic.

Adjacent completed-candle forecasts can reverse for legitimate market reasons.
This audit does not establish model instability, provider authenticity, trading
edge, delivery, or permission to submit simulated or live orders.
"""
from collections import defaultdict
import math

from .forecast_decision_coverage import audit_forecast_decision_coverage


def _direction(probability, neutral_band):
    if probability is None or 0.5 - neutral_band <= probability <= 0.5 + neutral_band:
        return 0
    return 1 if probability > 0.5 else -1


def _transitions(ordered_bases, probabilities, seconds, neutral_band, strong_band):
    """Count only consecutive signed forecast pairs, never bridge gaps/abstentions."""
    eligible = flips = strong = longest = run = 0
    bounds = None
    run_start = None
    max_jump = 0.0
    previous_base = previous_p = None
    for base in ordered_bases:
        p = probabilities.get(base)
        signed = _direction(p, neutral_band)
        previous_signed = _direction(previous_p, neutral_band)
        adjacent = previous_base is not None and base - previous_base == seconds
        if adjacent and signed and previous_signed:
            eligible += 1
            max_jump = max(max_jump, abs(p - previous_p))
            if signed != previous_signed:
                flips += 1
                if abs(p - 0.5) >= strong_band and abs(previous_p - 0.5) >= strong_band:
                    strong += 1
                if run == 0:
                    run_start = previous_base
                run += 1
                if run > longest:
                    longest = run
                    bounds = [run_start, base]
            else:
                run = 0
        else:
            run = 0
        previous_base, previous_p = base, p
    return {"eligibleAdjacentSignedPairs": eligible,
            "directionReversalCount": flips,
            "strongReversalCount": strong,
            "longestConsecutiveReversalPairs": longest,
            "longestReversalRunBaseStarts": bounds,
            "trailingConsecutiveReversalPairs": run,
            "largestAdjacentSignedProbabilityJump": max_jump if eligible else None}


def audit_forecast_direction_reversals(
        snapshot, expected_identity, expected_keys, abstentions, *, as_of,
        min_decisions_per_group=60, min_adjacent_signed_pairs=30,
        neutral_band=0.05, strong_band=0.10, warning_reversal_fraction=0.40):
    """Describe direction changes on a complete caller-declared decision census.

    A reversal is between p < 0.5-neutral_band and p > 0.5+neutral_band.
    p at either neutral boundary is neutral, not a directional forecast.
    'Strong' uses both endpoints at least strong_band from 0.5. Thresholds
    are descriptive review heuristics, not a significance test or signal.
    """
    if (type(min_decisions_per_group) is not int or
            not 30 <= min_decisions_per_group <= 5000 or
            type(min_adjacent_signed_pairs) is not int or
            not 30 <= min_adjacent_signed_pairs <= 4999):
        raise ValueError("Invalid direction-reversal population threshold")
    for value in (neutral_band, strong_band, warning_reversal_fraction):
        if type(value) not in (int, float) or not math.isfinite(value):
            raise ValueError("Invalid direction-reversal warning threshold")
    if (not 0 <= neutral_band < strong_band < 0.5 or
            not 0 <= warning_reversal_fraction <= 1):
        raise ValueError("Invalid direction-reversal probability bands")
    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_FORECAST_AND_DECISION_CENSUS_UNVERIFIED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": coverage["expectedCount"],
        "minDecisionsPerGroup": min_decisions_per_group,
        "minAdjacentSignedPairs": min_adjacent_signed_pairs,
        "neutralProbabilityBand": float(neutral_band),
        "strongProbabilityBand": float(strong_band),
        "warningReversalFraction": float(warning_reversal_fraction),
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithWarning": None,
        "byModelHorizon": [],
        "sourceAuthenticated": False,
        "scheduleIndependentlyVerified": False,
        "abstentionsIndependentlyVerified": False,
        "forecastOutcomesAuthenticated": False,
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
        if len(ordered) < min_decisions_per_group:
            insufficient += 1
            continue
        probabilities = forecast_groups[(model, horizon)]
        metrics = _transitions(ordered, probabilities, expected_identity["seconds"],
                               neutral_band, strong_band)
        pairs = metrics["eligibleAdjacentSignedPairs"]
        if pairs < min_adjacent_signed_pairs:
            insufficient += 1
            continue
        fraction = metrics["directionReversalCount"] / pairs
        warning = fraction >= warning_reversal_fraction
        warnings += int(warning)
        result["byModelHorizon"].append({
            "modelVersion": model,
            "horizonCandles": horizon,
            "expectedDecisionCount": len(ordered),
            "forecastCount": len(probabilities),
            "abstentionCount": len(ordered) - len(probabilities),
            "neutralForecastCount": sum(
                _direction(p, neutral_band) == 0 for p in probabilities.values()),
            **metrics,
            "directionReversalFractionOfEligiblePairs": fraction,
            "reversalFractionMeetsWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithWarning"] = warnings
    result["status"] = (
        "OPERATOR_REVIEW_REQUIRED" if warnings else
        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
        "DECLARED_DIRECTION_REVERSALS_WITHIN_WARNING_UNVERIFIED")
    return result
