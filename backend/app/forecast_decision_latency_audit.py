"""Offline timing audit of declared completed-candle forecast/abstention decisions.

This is not a clock attestation, market feed, alert sender or order engine.
"""
import math

from .forecast_decision_coverage import audit_forecast_decision_coverage

_HORIZONS = (1, 3, 12)
_MAX_SAMPLE = 50


def _nearest_rank(values, percentile):
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered)) - 1]


def audit_forecast_decision_latency(snapshot, expected_identity, expected_keys,
                                    abstentions, *, as_of, warning_seconds=15,
                                    min_complete=30):
    """Audit declared decision latency after completed candle close.

    Expected keys must be registered independently. A recorded decision is
    timely only when its *declared* time is within warning_seconds of close.
    A missing decision is overdue only after the entire permissible issuance
    window has elapsed. Missing/conflicting/unexpected records withhold all
    percentile metrics, never silently shrinking the measured population.
    """
    if type(warning_seconds) is not int or not 0 <= warning_seconds <= 3600:
        raise ValueError("Invalid decision warning threshold")
    if type(min_complete) is not int or not 30 <= min_complete <= 5000:
        raise ValueError("Invalid minimum complete decision population")

    # Validates source identity, event/forecast consistency, decision clocks,
    # unique expected keys, explicit abstention reasons and population coverage.
    coverage = audit_forecast_decision_coverage(
        snapshot, expected_identity, expected_keys, abstentions, as_of=as_of)
    seconds = expected_identity["seconds"]
    lag_limit = snapshot["maxLagSeconds"]
    if warning_seconds > min(lag_limit, seconds - 1):
        raise ValueError("Decision warning exceeds permissible issuance window")

    expected = {tuple(k) for k in expected_keys}
    forecast_times = {(r["modelVersion"], r["horizon"], r["baseStart"]): r["issuedAt"]
                      for r in snapshot["forecasts"]}
    abstention_times = {(r["modelVersion"], r["horizon"], r["baseStart"]): r["decisionAt"]
                       for r in abstentions}
    groups = {h: {"expected": 0, "forecast": 0, "abstention": 0,
                  "missing": 0, "missingOverdue": 0, "late": 0,
                  "timely": 0, "lags": []} for h in _HORIZONS}
    missing_overdue_keys = []
    missing_within_window = 0
    for key in sorted(expected):
        _model, horizon, base = key
        group = groups[horizon]
        group["expected"] += 1
        has_forecast = key in forecast_times
        has_abstention = key in abstention_times
        if has_forecast == has_abstention:
            # Either absent or contradictory. Never use a conflicting timestamp.
            if not has_forecast:
                group["missing"] += 1
                deadline = min(base + seconds + lag_limit, base + 2 * seconds - 1)
                if as_of > deadline:
                    group["missingOverdue"] += 1
                    missing_overdue_keys.append(key)
                else:
                    missing_within_window += 1
            continue
        at = forecast_times[key] if has_forecast else abstention_times[key]
        group["forecast" if has_forecast else "abstention"] += 1
        latency = at - (base + seconds)
        group["lags"].append(latency)
        if latency > warning_seconds:
            group["late"] += 1
        else:
            group["timely"] += 1

    complete = coverage["status"] == "DECLARED_DECISIONS_MATCH_UNVERIFIED"
    total = sum(g["expected"] for g in groups.values())
    lags = [lag for g in groups.values() for lag in g["lags"]]
    late_count = sum(g["late"] for g in groups.values())
    timely_count = sum(g["timely"] for g in groups.values())
    summary_ready = complete and total >= min_complete
    rows = []
    for horizon in _HORIZONS:
        g = groups[horizon]
        if not g["expected"]:
            continue
        horizon_ready = complete and g["expected"] >= min_complete
        rows.append({
            "horizonCandles": horizon,
            "expectedCount": g["expected"],
            "recordedForecastCount": g["forecast"],
            "recordedAbstentionCount": g["abstention"],
            "missingCount": g["missing"],
            "missingPastDeadlineCount": g["missingOverdue"],
            "lateRecordedDecisionCount": g["late"],
            "withinWarningBudgetCount": g["timely"],
            "p95DeclaredLatencySeconds": _nearest_rank(g["lags"], .95) if horizon_ready else None,
            "maxDeclaredLatencySeconds": max(g["lags"]) if horizon_ready else None,
        })
    needs_review = (not complete or late_count > 0 or bool(missing_overdue_keys))
    return {
        "status": ("NO_DECLARED_EXPECTATIONS" if not total and
                   coverage["status"] == "NO_DECLARED_EXPECTATIONS" else
                   "OPERATOR_REVIEW_REQUIRED" if needs_review else
                   "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE" if not summary_ready else
                   "DECLARED_TIMING_WITHIN_BUDGET_UNVERIFIED"),
        "evidence": "CALLER_DECLARED_TIMESTAMPS_AND_SCHEDULE_NOT_INDEPENDENTLY_ATTESTED",
        "evaluationAsOfDeclared": as_of,
        "warningSecondsAfterCandleClose": warning_seconds,
        "minCompleteForPercentiles": min_complete,
        "decisionCoverageStatus": coverage["status"],
        "expectedCount": total,
        "recordedExactlyOnceCount": coverage["coveredExactlyOnceCount"],
        "lateRecordedDecisionCount": late_count,
        "withinWarningBudgetCount": timely_count,
        "withinBudgetFractionOfExpected": timely_count / total if total else None,
        "missingPastDeadlineCount": len(missing_overdue_keys),
        "missingStillWithinWindowCount": missing_within_window,
        "missingPastDeadlineKeysFirst50": [list(k) for k in missing_overdue_keys[:_MAX_SAMPLE]],
        "truncatedMissingPastDeadlineKeys": len(missing_overdue_keys) > _MAX_SAMPLE,
        "p50DeclaredLatencySeconds": _nearest_rank(lags, .5) if summary_ready else None,
        "p95DeclaredLatencySeconds": _nearest_rank(lags, .95) if summary_ready else None,
        "maxDeclaredLatencySeconds": max(lags) if summary_ready else None,
        "byHorizon": rows,
        "sourceAuthenticated": False,
        "decisionClockAuthenticated": False,
        "scheduleIndependentlyVerified": False,
        "abstentionsIndependentlyVerified": False,
        "recipientDeliveryVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
