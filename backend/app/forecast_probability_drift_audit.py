"""Disconnected, declared-only chronological forecast probability-mix audit.

No independent provider attestation, scheduler, notification, broker, or orders.
A complete declared decision census is required before reporting distributions.
"""

import math
from collections import defaultdict

from .forecast_decision_coverage import audit_forecast_decision_coverage

_BINS = 5


def _histogram(probabilities):
    counts = [0] * _BINS
    for probability in probabilities:
        # The underlying replay-validated scorecard requires 0 < p < 1.
        counts[min(_BINS - 1, int(probability * _BINS))] += 1
    return counts


def _jensen_shannon_nats(early, late):
    """Symmetric, finite divergence for nonempty fixed-bin count vectors."""
    n, m = sum(early), sum(late)
    p = [value / n for value in early]
    q = [value / m for value in late]
    mid = [(a + b) / 2 for a, b in zip(p, q)]
    return max(0.0, sum(
        (a * math.log(a / midpoint) if a else 0.0)
        + (b * math.log(b / midpoint) if b else 0.0)
        for a, b, midpoint in zip(p, q, mid)) / 2)


def audit_forecast_probability_drift(
        snapshot, expected_identity, expected_keys, abstentions, *, as_of,
        min_decisions_per_half=30, min_forecasts_per_half=30,
        warning_js_nats=0.10):
    """Compare early/late issued probability distributions per model/horizon.

    First reconcile *all* expected forecast-or-abstention decisions. Split by
    completed base-candle chronology, not issuance arrival order or outcome.
    Withhold a group unless each half has sufficient decisions and forecasts.
    This is a descriptive distribution shift, not proof of model drift or edge.
    """
    if (type(min_decisions_per_half) is not int
            or not 30 <= min_decisions_per_half <= 2500):
        raise ValueError("Invalid minimum decision count per half")
    if (type(min_forecasts_per_half) is not int
            or not 30 <= min_forecasts_per_half <= 2500):
        raise ValueError("Invalid minimum forecast count per half")
    if (type(warning_js_nats) not in (int, float)
            or not math.isfinite(warning_js_nats)
            or not 0 <= warning_js_nats <= math.log(2)):
        raise ValueError("Invalid Jensen-Shannon warning threshold")

    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_FORECASTS_ABSTENTIONS_AND_SCHEDULE_UNVERIFIED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": coverage["expectedCount"],
        "fixedProbabilityBins": [[0.0, 0.2], [0.2, 0.4], [0.4, 0.6],
                                 [0.6, 0.8], [0.8, 1.0]],
        "minDecisionsPerChronologicalHalf": min_decisions_per_half,
        "minForecastsPerChronologicalHalf": min_forecasts_per_half,
        "warningJensenShannonNats": float(warning_js_nats),
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithWarning": None,
        "maxJensenShannonNats": None,
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

    forecast_probabilities = {
        (r["modelVersion"], r["horizon"], r["baseStart"]): r["probability"]
        for r in snapshot["forecasts"]
    }
    grouped = defaultdict(list)
    for model, horizon, base in expected_keys:
        grouped[(model, horizon)].append(base)

    insufficient = 0
    warnings = 0
    maximum = None
    for (model, horizon), bases in sorted(grouped.items()):
        ordered = sorted(bases)
        middle = len(ordered) // 2
        halves = (ordered[:middle], ordered[middle:])
        if any(len(half) < min_decisions_per_half for half in halves):
            insufficient += 1
            continue
        probabilities = [[forecast_probabilities[(model, horizon, base)]
                          for base in half if (model, horizon, base) in forecast_probabilities]
                         for half in halves]
        if any(len(half) < min_forecasts_per_half for half in probabilities):
            insufficient += 1
            continue
        early_counts, late_counts = map(_histogram, probabilities)
        divergence = _jensen_shannon_nats(early_counts, late_counts)
        warning = divergence > warning_js_nats
        warnings += int(warning)
        maximum = divergence if maximum is None else max(maximum, divergence)
        result["byModelHorizon"].append({
            "modelVersion": model,
            "horizonCandles": horizon,
            "earlyDecisionCount": len(halves[0]),
            "lateDecisionCount": len(halves[1]),
            "earlyFirstBaseStart": halves[0][0],
            "earlyLastBaseStart": halves[0][-1],
            "lateFirstBaseStart": halves[1][0],
            "lateLastBaseStart": halves[1][-1],
            "earlyForecastCount": len(probabilities[0]),
            "lateForecastCount": len(probabilities[1]),
            "earlyAbstentionCount": len(halves[0]) - len(probabilities[0]),
            "lateAbstentionCount": len(halves[1]) - len(probabilities[1]),
            "earlyAbstentionRate": 1 - len(probabilities[0]) / len(halves[0]),
            "lateAbstentionRate": 1 - len(probabilities[1]) / len(halves[1]),
            "earlyFixedBinCounts": early_counts,
            "lateFixedBinCounts": late_counts,
            "jensenShannonNats": divergence,
            "divergenceExceedsWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithWarning"] = warnings
    result["maxJensenShannonNats"] = maximum
    result["status"] = (
        "OPERATOR_REVIEW_REQUIRED" if warnings else
        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
        "DECLARED_PROBABILITY_MIX_WITHIN_WARNING_UNVERIFIED")
    return result
