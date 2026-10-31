"""Disconnected audit of declared abstention-reason composition over time.

The source, decision schedule, abstentions and clock are caller-declared. This
module cannot authenticate them, dispatch notifications or authorize orders.
"""
from collections import Counter, defaultdict
import math

from .forecast_decision_coverage import audit_forecast_decision_coverage

_REASONS = ("DATA_QUALITY", "LOW_CONFIDENCE", "MODEL_UNAVAILABLE", "OTHER", "POLICY_HOLD")


def audit_forecast_abstention_reason_mix(
        snapshot, expected_identity, expected_keys, abstentions, *, as_of,
        min_decisions_per_half=30, min_abstentions_per_half=20,
        warning_total_variation=0.25):
    """Compare abstention-reason composition in chronological decision halves.

    An entire incomplete census withholds *all* statistics. Group-level
    insufficient abstentions withhold that group's conditional reason mix.
    A stable conditional mix does not imply a stable abstention rate.
    """
    if (type(min_decisions_per_half) is not int
            or not 30 <= min_decisions_per_half <= 2500):
        raise ValueError("Invalid minimum decisions per half")
    if (type(min_abstentions_per_half) is not int
            or not 20 <= min_abstentions_per_half <= 2500):
        raise ValueError("Invalid minimum abstentions per half")
    if (type(warning_total_variation) not in (int, float)
            or not math.isfinite(warning_total_variation)
            or not 0 <= warning_total_variation <= 1):
        raise ValueError("Invalid total-variation threshold")
    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_DECISIONS_ABSTENTIONS_AND_SCHEDULE_UNVERIFIED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": coverage["expectedCount"],
        "reasonOrder": list(_REASONS),
        "minDecisionsPerChronologicalHalf": min_decisions_per_half,
        "minAbstentionsPerChronologicalHalf": min_abstentions_per_half,
        "warningTotalVariation": float(warning_total_variation),
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithWarning": None,
        "maxTotalVariation": None,
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

    reasons_by_key = {
        (a["modelVersion"], a["horizon"], a["baseStart"]): a["reason"]
        for a in abstentions
    }
    groups = defaultdict(list)
    for model, horizon, base in expected_keys:
        groups[(model, horizon)].append(base)
    insufficient = warnings = 0
    max_tv = None
    for (model, horizon), bases in sorted(groups.items()):
        ordered = sorted(bases)
        mid = len(ordered) // 2
        halves = (ordered[:mid], ordered[mid:])
        if any(len(half) < min_decisions_per_half for half in halves):
            insufficient += 1
            continue
        counts = []
        for half in halves:
            observed = Counter(reasons_by_key[(model, horizon, base)]
                               for base in half if (model, horizon, base) in reasons_by_key)
            counts.append([observed[reason] for reason in _REASONS])
        ns = [sum(c) for c in counts]
        if any(n < min_abstentions_per_half for n in ns):
            insufficient += 1
            continue
        tv = 0.5 * sum(abs(a / ns[0] - b / ns[1])
                       for a, b in zip(counts[0], counts[1]))
        # Mathematical rounding must never make a bounded distance > 1.
        tv = min(1.0, max(0.0, tv))
        warning = tv > warning_total_variation
        warnings += int(warning)
        max_tv = tv if max_tv is None else max(max_tv, tv)
        result["byModelHorizon"].append({
            "modelVersion": model, "horizonCandles": horizon,
            "earlyDecisionCount": len(halves[0]),
            "lateDecisionCount": len(halves[1]),
            "earlyFirstBaseStart": halves[0][0],
            "earlyLastBaseStart": halves[0][-1],
            "lateFirstBaseStart": halves[1][0],
            "lateLastBaseStart": halves[1][-1],
            "earlyAbstentionCount": ns[0],
            "lateAbstentionCount": ns[1],
            "earlyAbstentionRate": ns[0] / len(halves[0]),
            "lateAbstentionRate": ns[1] / len(halves[1]),
            "earlyReasonCounts": counts[0],
            "lateReasonCounts": counts[1],
            "totalVariation": tv,
            "compositionExceedsWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithWarning"] = warnings
    result["maxTotalVariation"] = max_tv
    result["status"] = (
        "OPERATOR_REVIEW_REQUIRED" if warnings else
        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
        "DECLARED_REASON_MIX_WITHIN_WARNING_UNVERIFIED")
    return result
