"""Disconnected census of expected versus recorded completed-candle forecasts.

A caller-declared issuance register is NOT an independently verified schedule.
This audit has no network, storage, notification, fill or order side effects.
"""
import re

from .forecast_prospective_scorecard import summarize_forecast_snapshot

_MAX = 5000
_MAX_EPOCH = 2**53 - 1
_MODEL = re.compile(r"[A-Za-z0-9_.:-]{1,80}\Z")


def _valid_key(key, seconds, as_of):
    if type(key) not in (list, tuple) or len(key) != 3:
        return False
    model, horizon, base = key
    return (type(model) is str and _MODEL.fullmatch(model) is not None
            and type(horizon) is int and horizon in (1, 3, 12)
            and type(base) is int and 0 <= base <= _MAX_EPOCH - seconds
            and base % seconds == 0 and base + seconds <= as_of)


def audit_forecast_issuance_coverage(snapshot, expected_identity, expected_keys, *, as_of):
    """Compare a predeclared issuance schedule with a validated journal snapshot.

    The expected keys are (modelVersion, horizonCandles, baseStart). A caller
    must register intended issuances independently of the observed journal;
    this function cannot prove that independence or market-session coverage.
    A pending forecast is still an issuance, never a successful outcome.
    """
    if type(as_of) is not int or not 0 <= as_of <= _MAX_EPOCH:
        raise ValueError("Invalid declared issuance audit cutoff")
    if type(expected_keys) is not list or len(expected_keys) > _MAX:
        raise ValueError("Invalid bounded expected issuance register")
    # Validates event/forecast identity, resolution, chronology and source
    # isolation before any reconciliation or positive status is reported.
    validated = summarize_forecast_snapshot(snapshot)
    identity = validated["identity"]
    if type(expected_identity) is not dict or expected_identity != identity:
        raise ValueError("Expected issuance source identity mismatch")
    seconds = identity["seconds"]
    expected = set()
    for key in expected_keys:
        if not _valid_key(key, seconds, as_of):
            raise ValueError("Invalid or incomplete expected forecast candle")
        normalized = tuple(key)
        if normalized in expected:
            raise ValueError("Duplicate expected forecast issuance")
        expected.add(normalized)
    observed = set()
    for row in snapshot["forecasts"]:
        key = (row["modelVersion"], row["horizon"], row["baseStart"])
        if not _valid_key(key, seconds, as_of) or row["issuedAt"] > as_of:
            raise ValueError("Invalid or future observed forecast issuance")
        if key in observed:
            raise ValueError("Duplicate observed model/horizon/base issuance")
        observed.add(key)
    missing = sorted(expected - observed)
    unexpected = sorted(observed - expected)
    return {
        "status": ("OPERATOR_REVIEW_REQUIRED" if missing or unexpected else
                   "NO_DECLARED_EXPECTATIONS" if not expected else
                   "DECLARED_MATCH_UNVERIFIED"),
        "evidence": "CALLER_DECLARED_ISSUANCE_REGISTER_NOT_INDEPENDENTLY_ATTESTED",
        "evaluationAsOfDeclared": as_of,
        "expectedCount": len(expected),
        "observedCount": len(observed),
        "missingCount": len(missing),
        "unexpectedCount": len(unexpected),
        "missingKeysFirst50": [list(key) for key in missing[:50]],
        "unexpectedKeysFirst50": [list(key) for key in unexpected[:50]],
        "truncatedKeyLists": len(missing) > 50 or len(unexpected) > 50,
        "sourceAuthenticated": False,
        "scheduleIndependentlyVerified": False,
        "forecastDeliveryVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
