"""Read-only, caller-declared consecutive forecast abstention audit.

Never authenticates schedules, sends alerts, fills paper orders or trades.
"""
from collections import defaultdict

from .forecast_decision_coverage import audit_forecast_decision_coverage


def _streaks(bases, reasons, seconds):
    """Streaks require adjacent expected candle starts, not merely adjacent rows."""
    longest = longest_span = 0
    longest_bounds = None
    same_reason = same_reason_span = 0
    same_reason_bounds = None
    same_reason_label = None
    start = reason_start = previous = reason_label = None
    for base in bases:
        reason = reasons.get(base)
        if previous is not None and base - previous != seconds:
            longest = 0
            same_reason = 0
            reason_label = None
        previous = base
        if reason is None:
            longest = 0
            same_reason = 0
            reason_label = None
            continue
        if not longest:
            start = base
        longest += 1
        if longest > longest_span:
            longest_span = longest
            longest_bounds = [start, base]
        if reason != reason_label or not same_reason:
            same_reason = 0
            reason_start = base
        same_reason += 1
        reason_label = reason
        if same_reason > same_reason_span:
            same_reason_span = same_reason
            same_reason_bounds = [reason_start, base]
            same_reason_label = reason
    return {
        "longestAbstentionStreak": longest_span,
        "longestAbstentionStreakBaseStarts": longest_bounds,
        "longestSameReasonStreak": same_reason_span,
        "longestSameReasonStreakReason": same_reason_label,
        "longestSameReasonStreakBaseStarts": same_reason_bounds,
        "trailingAbstentionStreak": longest,
        "trailingSameReasonStreak": same_reason,
        "trailingSameReason": reason_label if same_reason else None,
    }


def audit_forecast_abstention_streaks(
        snapshot, expected_identity, expected_keys, abstentions, *, as_of,
        min_decisions_per_group=30, warning_consecutive_abstentions=12):
    """Audit stuck-abstention runs against a complete declared decision census.

    The expected schedule must be registered independently in any future
    operational integration. A declared-only match is NOT verification.
    A missing, conflicting, unexpected or malformed decision withholds every
    streak rather than making a potentially selective subset look healthy.
    """
    if (type(min_decisions_per_group) is not int
            or not 30 <= min_decisions_per_group <= 5000):
        raise ValueError("Invalid minimum expected decision population")
    if (type(warning_consecutive_abstentions) is not int
            or not 2 <= warning_consecutive_abstentions <= 5000):
        raise ValueError("Invalid consecutive abstention warning threshold")
    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_DECISION_SCHEDULE_AND_ABSTENTIONS_UNVERIFIED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": coverage["expectedCount"],
        "minDecisionsPerGroup": min_decisions_per_group,
        "warningConsecutiveAbstentions": warning_consecutive_abstentions,
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithWarning": None,
        "byModelHorizon": [],
        "sourceAuthenticated": False,
        "scheduleIndependentlyVerified": False,
        "abstentionsIndependentlyVerified": False,
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

    grouped = defaultdict(list)
    for model, horizon, base in expected_keys:
        grouped[(model, horizon)].append(base)
    abstained = defaultdict(dict)
    for item in abstentions:
        abstained[(item["modelVersion"], item["horizon"])][item["baseStart"]] = item["reason"]
    insufficient = warnings = 0
    seconds = expected_identity["seconds"]
    for (model, horizon), bases in sorted(grouped.items()):
        ordered = sorted(bases)
        if len(ordered) < min_decisions_per_group:
            insufficient += 1
            continue
        reasons = abstained[(model, horizon)]
        streak = _streaks(ordered, reasons, seconds)
        warning = streak["longestAbstentionStreak"] >= warning_consecutive_abstentions
        warnings += int(warning)
        result["byModelHorizon"].append({
            "modelVersion": model,
            "horizonCandles": horizon,
            "expectedDecisionCount": len(ordered),
            "forecastCount": len(ordered) - len(reasons),
            "abstentionCount": len(reasons),
            "firstExpectedBaseStart": ordered[0],
            "lastExpectedBaseStart": ordered[-1],
            "streakUnit": "ADJACENT_EXPECTED_CANDLE_STARTS",
            **streak,
            "streakExceedsOrMeetsWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithWarning"] = warnings
    result["status"] = (
        "OPERATOR_REVIEW_REQUIRED" if warnings else
        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
        "DECLARED_ABSTENTION_STREAKS_WITHIN_WARNING_UNVERIFIED")
    return result
