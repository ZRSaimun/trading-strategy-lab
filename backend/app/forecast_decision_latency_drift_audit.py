"""Disconnected chronological drift audit for completed-candle decision latency.

The schedule, source and decision timestamps are caller-declared, not independently
attested. This module cannot send alerts, simulate fills, or place orders.
"""
import math
from collections import defaultdict

from .forecast_decision_coverage import audit_forecast_decision_coverage


def _p95(values):
    ordered = sorted(values)
    return ordered[math.ceil(.95 * len(ordered)) - 1]


def audit_forecast_decision_latency_drift(
        snapshot, expected_identity, expected_keys, abstentions, *, as_of,
        min_per_half=30, warning_increase_seconds=10,
        decision_warning_seconds=15):
    """Compare the first and last chronological halves per model and horizon.

    No percentile is published until the *entire* expected decision population
    reconciles, including explicit abstentions. A rising p95 is a descriptive
    warning only, not a statistical drift test or trading authorization.
    """
    if type(min_per_half) is not int or not 30 <= min_per_half <= 2500:
        raise ValueError("Invalid minimum decision population per half")
    if (type(warning_increase_seconds) is not int
            or not 0 <= warning_increase_seconds <= 3600):
        raise ValueError("Invalid latency drift warning threshold")
    if (type(decision_warning_seconds) is not int
            or not 0 <= decision_warning_seconds <= 3600):
        raise ValueError("Invalid decision lateness threshold")

    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    seconds = expected_identity["seconds"]
    if decision_warning_seconds > min(snapshot["maxLagSeconds"], seconds - 1):
        raise ValueError("Lateness threshold exceeds issuance window")

    result = {
        "status": "OPERATOR_REVIEW_REQUIRED",
        "evidence": "CALLER_DECLARED_DECISION_TIMESTAMPS_AND_SCHEDULE_UNVERIFIED",
        "decisionCoverageStatus": coverage["status"],
        "evaluationAsOfDeclared": as_of,
        "expectedCount": coverage["expectedCount"],
        "minDecisionsPerChronologicalHalf": min_per_half,
        "warningP95IncreaseSeconds": warning_increase_seconds,
        "decisionLatenessSeconds": decision_warning_seconds,
        "eligibleModelHorizonGroups": 0,
        "insufficientModelHorizonGroups": None,
        "groupsWithP95IncreaseWarning": None,
        "maxP95IncreaseSeconds": None,
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
    if coverage["status"] != "DECLARED_DECISIONS_MATCH_UNVERIFIED":
        return result

    forecast_at = {
        (r["modelVersion"], r["horizon"], r["baseStart"]): r["issuedAt"]
        for r in snapshot["forecasts"]
    }
    abstention_at = {
        (r["modelVersion"], r["horizon"], r["baseStart"]): r["decisionAt"]
        for r in abstentions
    }
    groups = defaultdict(list)
    for model, horizon, base in expected_keys:
        key = (model, horizon, base)
        # The validated complete census proves exactly one of these exists.
        at = forecast_at[key] if key in forecast_at else abstention_at[key]
        groups[(model, horizon)].append((base, at - (base + seconds)))

    insufficient = 0
    warnings = 0
    max_increase = None
    for (model, horizon), entries in sorted(groups.items()):
        entries.sort()
        middle = len(entries) // 2
        if middle < min_per_half or len(entries) - middle < min_per_half:
            insufficient += 1
            continue
        early, late = entries[:middle], entries[middle:]
        early_lags = [lag for _, lag in early]
        late_lags = [lag for _, lag in late]
        early_p95, late_p95 = _p95(early_lags), _p95(late_lags)
        increase = late_p95 - early_p95
        warning = increase > warning_increase_seconds
        warnings += int(warning)
        max_increase = (increase if max_increase is None
                        else max(max_increase, increase))
        result["byModelHorizon"].append({
            "modelVersion": model,
            "horizonCandles": horizon,
            "earlyCount": len(early),
            "lateCount": len(late),
            "earlyFirstBaseStart": early[0][0],
            "earlyLastBaseStart": early[-1][0],
            "lateFirstBaseStart": late[0][0],
            "lateLastBaseStart": late[-1][0],
            "earlyP95DeclaredLatencySeconds": early_p95,
            "lateP95DeclaredLatencySeconds": late_p95,
            "lateMinusEarlyP95Seconds": increase,
            "earlyLateDecisionCount": sum(x > decision_warning_seconds for x in early_lags),
            "lateLateDecisionCount": sum(x > decision_warning_seconds for x in late_lags),
            "p95IncreaseExceedsWarning": warning,
        })
    result["eligibleModelHorizonGroups"] = len(result["byModelHorizon"])
    result["insufficientModelHorizonGroups"] = insufficient
    result["groupsWithP95IncreaseWarning"] = warnings
    result["maxP95IncreaseSeconds"] = max_increase
    result["status"] = (
        "OPERATOR_REVIEW_REQUIRED" if warnings else
        "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not result["byModelHorizon"] else
        "DECLARED_LATENCY_DRIFT_WITHIN_WARNING_UNVERIFIED")
    return result
