"""Offline, declared-only forecast/abstention decision census.

No provider, broker, database, scheduler, notification or order access.
Declared abstentions are NOT independently witnessed model decisions.
"""

from .forecast_issuance_coverage import audit_forecast_issuance_coverage, _valid_key, _MAX

_REASONS = frozenset({"DATA_QUALITY", "MODEL_UNAVAILABLE", "LOW_CONFIDENCE",
                      "POLICY_HOLD", "OTHER"})
_MAX_SAMPLE = 50


def audit_forecast_decision_coverage(snapshot, expected_identity, expected_keys,
                                     abstentions, *, as_of):
    """Reconcile a separately declared decision population against issuances.

    Each expected (modelVersion, horizon, baseStart) needs exactly one decision:
    a replay-validated journal forecast OR a caller-declared abstention. The
    journal and schedule remain unauthenticated; no execution is authorized.
    """
    issuance = audit_forecast_issuance_coverage(
        snapshot, expected_identity, expected_keys, as_of=as_of)
    if type(abstentions) is not list or len(abstentions) > _MAX:
        raise ValueError("Invalid bounded declared abstention population")
    seconds = expected_identity["seconds"]
    lag = snapshot["maxLagSeconds"]  # validated by the underlying scorecard
    expected = {tuple(key) for key in expected_keys}
    observed = {(row["modelVersion"], row["horizon"], row["baseStart"])
                for row in snapshot["forecasts"]}
    abstained = set()
    reasons = {}
    for item in abstentions:
        if type(item) is not dict or set(item) != {
                "modelVersion", "horizon", "baseStart", "decisionAt", "reason"}:
            raise ValueError("Malformed declared abstention")
        key = (item["modelVersion"], item["horizon"], item["baseStart"])
        if not _valid_key(key, seconds, as_of):
            raise ValueError("Invalid declared abstention key")
        at = item["decisionAt"]
        base = item["baseStart"]
        if (type(at) is not int or at < base + seconds
                or at > base + seconds + lag or at >= base + 2 * seconds
                or at > as_of):
            raise ValueError("Retroactive, stale or future declared abstention")
        reason = item["reason"]
        if type(reason) is not str or reason not in _REASONS:
            raise ValueError("Invalid declared abstention reason")
        if key in abstained:
            raise ValueError("Duplicate declared abstention")
        abstained.add(key)
        reasons[key] = reason

    conflicts = sorted(observed & abstained)
    missing = sorted(expected - observed - abstained)
    unexpected_abstentions = sorted(abstained - expected)
    unexpected_forecasts = sorted(observed - expected)
    valid_abstentions = (abstained & expected) - observed
    covered = ((observed & expected) - abstained) | valid_abstentions
    problems = bool(conflicts or missing or unexpected_abstentions or unexpected_forecasts)
    reason_counts = {reason: sum(reasons[k] == reason for k in valid_abstentions)
                     for reason in sorted(_REASONS)}
    return {
        "status": ("OPERATOR_REVIEW_REQUIRED" if problems else
                   "NO_DECLARED_EXPECTATIONS" if not expected else
                   "DECLARED_DECISIONS_MATCH_UNVERIFIED"),
        "evidence": "CALLER_DECLARED_ABSTENTIONS_AND_SCHEDULE_NOT_INDEPENDENTLY_ATTESTED",
        "evaluationAsOfDeclared": as_of,
        "expectedCount": len(expected),
        "forecastCount": issuance["observedCount"],
        "abstentionCount": len(abstained),
        "coveredExactlyOnceCount": len(covered),
        "missingDecisionCount": len(missing),
        "unexpectedForecastCount": len(unexpected_forecasts),
        "unexpectedAbstentionCount": len(unexpected_abstentions),
        "conflictingDecisionCount": len(conflicts),
        "declaredAbstentionRate": (len(valid_abstentions) / len(expected)
                                    if expected else None),
        "declaredValidAbstentionsByReason": reason_counts,
        "missingKeysFirst50": [list(k) for k in missing[:_MAX_SAMPLE]],
        "conflictingKeysFirst50": [list(k) for k in conflicts[:_MAX_SAMPLE]],
        "unexpectedForecastKeysFirst50": [list(k) for k in unexpected_forecasts[:_MAX_SAMPLE]],
        "unexpectedAbstentionKeysFirst50": [list(k) for k in unexpected_abstentions[:_MAX_SAMPLE]],
        "truncatedKeyLists": any(len(x) > _MAX_SAMPLE for x in
                                 (missing, conflicts, unexpected_forecasts,
                                  unexpected_abstentions)),
        "sourceAuthenticated": False,
        "scheduleIndependentlyVerified": False,
        "abstentionsIndependentlyVerified": False,
        "forecastDeliveryVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
