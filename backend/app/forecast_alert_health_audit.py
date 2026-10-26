"""Read-only declared-population health audit of disconnected forecast alerts.

Input states MUST first be decoded by ForecastAlertOutbox._unpack. This audit
cannot establish completeness, source authentication, or human delivery.
"""

from collections import Counter
import re

_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_STATES = {"QUEUED", "IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED", "CANCELLED"}
_FIELDS = {"version", "identity", "forecastId", "modelVersion", "horizon", "baseStart",
           "issueSeq", "issuedAt", "expiresAt", "status", "claimId", "claimedAt", "ackAt"}
_FEED_FIELDS = {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}
_MAX_ROWS = 1000


def _epoch(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _key(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _state_valid(state, now):
    if type(state) is not dict or set(state) != _FIELDS or state["version"] != 1 or type(state["version"]) is not int:
        return False
    feed = state["identity"]
    if type(feed) is not dict or set(feed) != _FEED_FIELDS:
        return False
    if any(type(feed[k]) is not str or not 1 <= len(feed[k]) <= 160 or feed[k] != feed[k].strip()
           for k in ("instrument", "provider", "venue", "sourceId")):
        return False
    if type(feed["priceSide"]) is not str or feed["priceSide"] not in ("bid", "ask", "mid"):
        return False
    if type(feed["seconds"]) is not int or not 60 <= feed["seconds"] <= 86400 or feed["seconds"] % 60:
        return False
    if not _key(state["forecastId"]) or not _key(state["modelVersion"]):
        return False
    if type(state["horizon"]) is not int or state["horizon"] not in (1, 3, 12):
        return False
    if type(state["issueSeq"]) is not int or state["issueSeq"] < 1:
        return False
    if any(not _epoch(state[k]) for k in ("baseStart", "issuedAt", "expiresAt")):
        return False
    if not state["baseStart"] <= state["issuedAt"] <= now or state["issuedAt"] > state["expiresAt"]:
        return False
    if type(state["status"]) is not str or state["status"] not in _STATES:
        return False
    if state["status"] in ("QUEUED", "CANCELLED"):
        return all(state[k] is None for k in ("claimId", "claimedAt", "ackAt"))
    claim = state["claimId"]
    if type(claim) is not str or len(claim) != 32 or any(c not in "0123456789abcdef" for c in claim):
        return False
    if not _epoch(state["claimedAt"]) or not state["issuedAt"] <= state["claimedAt"] < state["expiresAt"] or state["claimedAt"] > now:
        return False
    if state["status"] == "IN_FLIGHT_UNCERTAIN":
        return state["ackAt"] is None
    return (_epoch(state["ackAt"]) and state["claimedAt"] <= state["ackAt"] <= now)


def audit_forecast_alert_health(records, expected_keys, *, as_of,
                                queue_warning_seconds=60, uncertain_warning_seconds=30):
    """Audit a caller-declared exact alert population without sending anything.

    `records`: [{"sessionId": str, "state": unpacked_outbox_state}, ...]
    `expected_keys`: [(session_id, forecast_id), ...] from a *separate*
    registered inventory. Both inputs are still caller-declared, not attested.
    Missing, extra or duplicate keys reject the entire audit.
    """
    if not _epoch(as_of):
        raise ValueError("Invalid alert health audit time")
    if (type(queue_warning_seconds) is not int or not 1 <= queue_warning_seconds <= 3600 or
            type(uncertain_warning_seconds) is not int or not 1 <= uncertain_warning_seconds <= 3600):
        raise ValueError("Invalid alert health warning budget")
    if (type(records) is not list or type(expected_keys) is not list or
            len(records) > _MAX_ROWS or len(expected_keys) > _MAX_ROWS):
        raise ValueError("Invalid bounded alert health population")
    expected = set()
    for item in expected_keys:
        if type(item) not in (list, tuple) or len(item) != 2 or not all(_key(k) for k in item):
            raise ValueError("Invalid expected alert identity")
        key = tuple(item)
        if key in expected:
            raise ValueError("Duplicate expected alert identity")
        expected.add(key)
    seen = set()
    counts = Counter()
    oldest_queued = 0
    oldest_uncertain = 0
    max_ack_lag = 0
    warning_keys = []
    for record in records:
        if type(record) is not dict or set(record) != {"sessionId", "state"}:
            raise ValueError("Malformed alert health record")
        session, state = record["sessionId"], record["state"]
        if not _key(session) or not _state_valid(state, as_of):
            raise ValueError("Invalid alert health state")
        key = (session, state["forecastId"])
        if key in seen or key not in expected:
            raise ValueError("Duplicate or undeclared alert health record")
        seen.add(key)
        status = state["status"]
        if status == "QUEUED":
            if as_of >= state["expiresAt"]:
                counts["EXPIRED_UNCLAIMED"] += 1
                warning_keys.append(key)
            else:
                counts["QUEUED"] += 1
                age = as_of - state["issuedAt"]
                oldest_queued = max(oldest_queued, age)
                if age >= queue_warning_seconds:
                    counts["QUEUE_DELAY_WARNING"] += 1
                    warning_keys.append(key)
        elif status == "IN_FLIGHT_UNCERTAIN":
            counts[status] += 1
            age = as_of - state["claimedAt"]
            oldest_uncertain = max(oldest_uncertain, age)
            if age >= uncertain_warning_seconds:
                counts["UNCERTAIN_DELAY_WARNING"] += 1
                warning_keys.append(key)
            if as_of >= state["expiresAt"]:
                counts["EXPIRED_IN_FLIGHT_UNCERTAIN"] += 1
                warning_keys.append(key)
        elif status == "ACK_RECORDED_UNVERIFIED":
            counts[status] += 1
            max_ack_lag = max(max_ack_lag, state["ackAt"] - state["claimedAt"])
            if state["ackAt"] >= state["expiresAt"]:
                counts["ACK_AT_OR_AFTER_EXPIRY_WARNING"] += 1
                warning_keys.append(key)
        else:
            counts["CANCELLED"] += 1
    if seen != expected:
        raise ValueError("Incomplete declared alert health population")
    statuses = ("QUEUED", "EXPIRED_UNCLAIMED", "IN_FLIGHT_UNCERTAIN",
                "EXPIRED_IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED",
                "ACK_AT_OR_AFTER_EXPIRY_WARNING", "CANCELLED",
                "QUEUE_DELAY_WARNING", "UNCERTAIN_DELAY_WARNING")
    requires_review = bool(counts["EXPIRED_UNCLAIMED"] or counts["IN_FLIGHT_UNCERTAIN"] or
                           counts["QUEUE_DELAY_WARNING"] or
                           counts["ACK_AT_OR_AFTER_EXPIRY_WARNING"])
    return {"populationEvidence": "DECLARED_ONLY_NOT_INDEPENDENTLY_VERIFIED",
            "status": "NO_DECLARED_ALERTS" if not expected else
                      "OPERATOR_REVIEW_REQUIRED" if requires_review else "DECLARED_ONLY",
            "declaredCount": len(expected), "counts": {name: counts[name] for name in statuses},
            "oldestQueuedSeconds": oldest_queued,
            "oldestUncertainSeconds": oldest_uncertain,
            "maxSelfAttestedAckLagSeconds": max_ack_lag,
            "warningKeys": [list(key) for key in sorted(set(warning_keys))],
            "providerDeliveryVerified": False, "recipientDeliveryVerified": False,
            "maySendNotification": False, "mayExecutePaperOrder": False,
            "mayExecuteLiveOrder": False}
