"""Disconnected chronological forecast-versus-abstention mix audit.

Caller-declared decisions and expected schedules are not authenticated.
This audit never authorizes a notification, simulated fill, or broker order.
"""

import math
from collections import defaultdict

from .forecast_decision_coverage import audit_forecast_decision_coverage

_REASONS = ("DATA_QUALITY", "LOW_CONFIDENCE", "MODEL_UNAVAILABLE", "OTHER", "POLICY_HOLD")


def audit_forecast_abstention_drift(snapshot, expected_identity, expected_keys,
                                    abstentions, *, as_of, min_per_half=30,
                                    warning_fraction=0.20):
    """Compare early/late declared abstention rates per (model, horizon).

    The entire expected decision census must reconcile exactly before *any*
    rates are published. This prevents selectively omitted hard periods from
    making the observed abstention rate appear reassuring. No statistical
    significance or causal model drift is inferred from a threshold crossing.
    """
    if type(min_per_half) is not int or not 30 <= min_per_half <= 2500:
        raise ValueError("Invalid minimum chronological half population")
    if (type(warning_fraction) not in (int, float)
            or not math.isfinite(warning_fraction)
            or not 0 <= warning_fraction <= 1):
        raise ValueError("Invalid abstention drift warning fraction")

    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    complete = coverage["status"] == "DECLARED_DECISIONS_MATCH_UNVERIFIED"
    expected_count = coverage["expectedCount"]
    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_SCHEDULE_AND_ABSTENTIONS_NOT_INDEPENDENTLY_ATTESTED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": expected_count,
        "minDecisionsPerChronologicalHalf": min_per_half,
        "warningAbsoluteRateChange": float(warning_fraction),
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithWarning": None,
        "maxAbsoluteDeclaredAbstentionRateChange": None,
        "byModelHorizon": [],
        "sourceAuthenticated": False,
        "decisionClockAuthenticated": False,
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
    if not complete:
        # No denominator, split or drift estimates from a partial population.
        return result

    groups = defaultdict(list)
    for model, horizon, base in expected_keys:
        groups[(model, horizon)].append(base)
    abstained = {(a["modelVersion"], a["horizon"], a["baseStart"]): a["reason"]
                 for a in abstentions}
    insufficient = 0
    warnings = 0
    max_delta = None
    for (model, horizon), bases in sorted(groups.items()):
        ordered = sorted(bases)
        middle = len(ordered) // 2
        if middle < min_per_half or len(ordered) - middle < min_per_half:
            insufficient += 1
            continue
        halves = (ordered[:middle], ordered[middle:])
        counts = []
        reasons = []
        for half in halves:
            selected = [abstained[(model, horizon, base)] for base in half
                        if (model, horizon, base) in abstained]
            counts.append(len(selected))
            reasons.append({reason: selected.count(reason) for reason in _REASONS})
        early_rate = counts[0] / len(halves[0])
        late_rate = counts[1] / len(halves[1])
        delta = late_rate - early_rate
        warning = abs(delta) > warning_fraction
        warnings += int(warning)
        max_delta = abs(delta) if max_delta is None else max(max_delta, abs(delta))
        result["byModelHorizon"].append({
            "modelVersion": model,
            "horizonCandles": horizon,
            "earlyCount": len(halves[0]),
            "lateCount": len(halves[1]),
            "earlyFirstBaseStart": halves[0][0],
            "earlyLastBaseStart": halves[0][-1],
            "lateFirstBaseStart": halves[1][0],
            "lateLastBaseStart": halves[1][-1],
            "earlyAbstentions": counts[0],
            "lateAbstentions": counts[1],
            "earlyAbstentionRate": early_rate,
            "lateAbstentionRate": late_rate,
            "lateMinusEarlyAbstentionRate": delta,
            "earlyReasons": reasons[0],
            "lateReasons": reasons[1],
            "absoluteChangeExceedsWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithWarning"] = warnings
    result["maxAbsoluteDeclaredAbstentionRateChange"] = max_delta
    result["status"] = ("OPERATOR_REVIEW_REQUIRED" if warnings else
                        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
                        "DECLARED_ABSTENTION_MIX_WITHIN_WARNING_UNVERIFIED")
    return result
