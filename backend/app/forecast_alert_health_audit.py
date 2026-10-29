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
    # Outbox.queue caps age at 3,600 seconds and never permits zero lifetime.
    # Reject impossible persisted expiries rather than reporting false health.
    if (not state["baseStart"] <= state["issuedAt"] <= now or
            not state["issuedAt"] < state["expiresAt"] <= state["issuedAt"] + 3600):
        return False
    # ForecastEventStore only issues after the base candle completes and
    # before the following candle completes. Outbox.queue never advertises
    # expiry beyond the target candle's completion, even for long TTLs.
    seconds, base = feed["seconds"], state["baseStart"]
    target_end = base + (state["horizon"] + 1) * seconds
    if (base % seconds or target_end > 2**53 - 1 or
            not base + seconds <= state["issuedAt"] < base + 2 * seconds or
            state["expiresAt"] > target_end):
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
                                queue_warning_seconds=60, uncertain_warning_seconds=30,
                                expiry_warning_seconds=30, unverified_ack_warning_seconds=300):
    """Audit a caller-declared exact alert population without sending anything.

    `records`: [{"sessionId": str, "state": unpacked_outbox_state}, ...]
    `expected_keys`: [(session_id, forecast_id), ...] from a *separate*
    registered inventory. Both inputs are still caller-declared, not attested.
    Missing, extra or duplicate keys reject the entire audit.
    """
    if not _epoch(as_of):
        raise ValueError("Invalid alert health audit time")
    if (type(queue_warning_seconds) is not int or not 1 <= queue_warning_seconds <= 3600 or
            type(uncertain_warning_seconds) is not int or not 1 <= uncertain_warning_seconds <= 3600 or
            type(expiry_warning_seconds) is not int or not 1 <= expiry_warning_seconds <= 3600 or
            type(unverified_ack_warning_seconds) is not int or not 1 <= unverified_ack_warning_seconds <= 3600):
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
    # A claim token is a one-attempt correlation identity, not merely a
    # per-forecast field. Reuse across alerts makes receipt attribution
    # ambiguous even when the alert keys themselves are distinct.
    claimed_ids = set()
    counts = Counter()
    oldest_queued = 0
    earliest_queued_expiry = None
    earliest_queued_keys = []
    next_queue_delay_warning = None
    next_queue_delay_keys = []
    oldest_uncertain = 0
    max_ack_lag = 0
    oldest_unverified_ack = 0
    next_ack_escalation = None
    next_ack_escalation_keys = []
    warning_keys = []
    warning_reason_map = {}
    unverified_ack_keys = []
    unverified_ack_ages = {}

    def warn(key, reason):
        warning_keys.append(key)
        warning_reason_map.setdefault(key, set()).add(reason)
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
        claim_id = state["claimId"]
        if claim_id is not None:
            if claim_id in claimed_ids:
                raise ValueError("Reused forecast alert claim ID")
            claimed_ids.add(claim_id)
        status = state["status"]
        if status == "QUEUED":
            if as_of >= state["expiresAt"]:
                counts["EXPIRED_UNCLAIMED"] += 1
                warn(key, "EXPIRED_UNCLAIMED")
            else:
                counts["QUEUED"] += 1
                # Triage the first unclaimed alert that will expire. Never
                # treat this countdown as authorization to bypass send gates.
                remaining = state["expiresAt"] - as_of
                if earliest_queued_expiry is None or remaining < earliest_queued_expiry:
                    earliest_queued_expiry = remaining
                    earliest_queued_keys = [key]
                elif remaining == earliest_queued_expiry:
                    earliest_queued_keys.append(key)
                age = as_of - state["issuedAt"]
                oldest_queued = max(oldest_queued, age)
                if age >= queue_warning_seconds:
                    counts["QUEUE_DELAY_WARNING"] += 1
                    warn(key, "QUEUE_DELAY_WARNING")
                elif state["issuedAt"] + queue_warning_seconds < state["expiresAt"]:
                    # A queued alert that expires at/before its age threshold
                    # can NEVER reach QUEUE_DELAY_WARNING: expiry wins at the
                    # exact boundary. Do not advertise an impossible future
                    # incident deadline in the operator timeline.
                    remaining_delay = queue_warning_seconds - age
                    if (next_queue_delay_warning is None or
                            remaining_delay < next_queue_delay_warning):
                        next_queue_delay_warning = remaining_delay
                        next_queue_delay_keys = [key]
                    elif remaining_delay == next_queue_delay_warning:
                        next_queue_delay_keys.append(key)
                # Short-lived alerts may approach expiry before the normal
                # queue-age threshold. Surface them for operator review early.
                if state["expiresAt"] - as_of <= expiry_warning_seconds:
                    counts["EXPIRING_SOON_WARNING"] += 1
                    warn(key, "EXPIRING_SOON_WARNING")
        elif status == "IN_FLIGHT_UNCERTAIN":
            counts[status] += 1
            # Every uncertain send requires reconciliation, even before its
            # age-warning budget. Otherwise OPERATOR_REVIEW_REQUIRED could
            # return no actionable identity for a freshly claimed alert.
            warn(key, "IN_FLIGHT_UNCERTAIN")
            age = as_of - state["claimedAt"]
            oldest_uncertain = max(oldest_uncertain, age)
            if age >= uncertain_warning_seconds:
                counts["UNCERTAIN_DELAY_WARNING"] += 1
                warn(key, "UNCERTAIN_DELAY_WARNING")
            if as_of >= state["expiresAt"]:
                counts["EXPIRED_IN_FLIGHT_UNCERTAIN"] += 1
                warn(key, "EXPIRED_IN_FLIGHT_UNCERTAIN")
        elif status == "ACK_RECORDED_UNVERIFIED":
            counts[status] += 1
            # A timely self-attested ACK is not independent provider/device
            # delivery evidence. Retain its identity for later reconciliation
            # without conflating it with an age/expiry warning.
            unverified_ack_keys.append(key)
            max_ack_lag = max(max_ack_lag, state["ackAt"] - state["claimedAt"])
            ack_age = as_of - state["ackAt"]
            unverified_ack_ages[key] = ack_age
            oldest_unverified_ack = max(oldest_unverified_ack, ack_age)
            # Only unbreached ACKs enter the next-deadline inventory. Already
            # overdue ACKs belong to warningKeys, not a misleading zero timer.
            if ack_age < unverified_ack_warning_seconds:
                remaining = unverified_ack_warning_seconds - ack_age
                if next_ack_escalation is None or remaining < next_ack_escalation:
                    next_ack_escalation = remaining
                    next_ack_escalation_keys = [key]
                elif remaining == next_ack_escalation:
                    next_ack_escalation_keys.append(key)
            # An unverified ACK can linger indefinitely without independent
            # provider/recipient evidence. Escalate aged entries for review,
            # without granting a retry or treating the ACK as delivered.
            if ack_age >= unverified_ack_warning_seconds:
                counts["ACK_RECONCILIATION_OVERDUE_WARNING"] += 1
                warn(key, "ACK_RECONCILIATION_OVERDUE_WARNING")
            if state["ackAt"] >= state["expiresAt"]:
                counts["ACK_AT_OR_AFTER_EXPIRY_WARNING"] += 1
                warn(key, "ACK_AT_OR_AFTER_EXPIRY_WARNING")
        else:
            counts["CANCELLED"] += 1
    if seen != expected:
        raise ValueError("Incomplete declared alert health population")
    statuses = ("QUEUED", "EXPIRED_UNCLAIMED", "IN_FLIGHT_UNCERTAIN",
                "EXPIRED_IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED",
                "ACK_AT_OR_AFTER_EXPIRY_WARNING", "ACK_RECONCILIATION_OVERDUE_WARNING", "CANCELLED",
                "QUEUE_DELAY_WARNING", "UNCERTAIN_DELAY_WARNING",
                "EXPIRING_SOON_WARNING")
    requires_review = bool(counts["EXPIRED_UNCLAIMED"] or counts["IN_FLIGHT_UNCERTAIN"] or
                           counts["QUEUE_DELAY_WARNING"] or counts["EXPIRING_SOON_WARNING"] or
                           counts["ACK_AT_OR_AFTER_EXPIRY_WARNING"] or
                           counts["ACK_RECONCILIATION_OVERDUE_WARNING"])
    return {"populationEvidence": "DECLARED_ONLY_NOT_INDEPENDENTLY_VERIFIED",
            "status": "NO_DECLARED_ALERTS" if not expected else
                      "OPERATOR_REVIEW_REQUIRED" if requires_review else "DECLARED_ONLY",
            "declaredCount": len(expected), "counts": {name: counts[name] for name in statuses},
            "oldestQueuedSeconds": oldest_queued,
            "earliestQueuedExpirySecondsRemaining": earliest_queued_expiry,
            "earliestQueuedExpiryKeys": [list(key) for key in sorted(earliest_queued_keys)],
            "nextQueueDelayWarningSecondsRemaining": next_queue_delay_warning,
            "nextQueueDelayWarningKeys": [list(key) for key in sorted(next_queue_delay_keys)],
            "oldestUncertainSeconds": oldest_uncertain,
            "maxSelfAttestedAckLagSeconds": max_ack_lag,
            "oldestUnverifiedAckAgeSeconds": oldest_unverified_ack,
            "nextUnverifiedAckEscalationSecondsRemaining": next_ack_escalation,
            "nextUnverifiedAckEscalationKeys": [list(key) for key in sorted(next_ack_escalation_keys)],
            "oldestUnverifiedAckKeys": [list(key) for key in sorted(
                key for key, age in unverified_ack_ages.items()
                if age == oldest_unverified_ack)],
            "warningKeys": [list(key) for key in sorted(set(warning_keys))],
            "warningReasons": [{"key": list(key), "reasons": sorted(reasons)}
                               for key, reasons in sorted(warning_reason_map.items())],
            "unverifiedAckKeys": [list(key) for key in sorted(unverified_ack_keys)],
            "providerDeliveryVerified": False, "recipientDeliveryVerified": False,
            "maySendNotification": False, "mayExecutePaperOrder": False,
            "mayExecuteLiveOrder": False}
