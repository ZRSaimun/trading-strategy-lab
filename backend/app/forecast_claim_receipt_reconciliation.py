"""Read-only cross-store audit of persisted forecast alert claims and send receipts.

This disconnected pure function cannot establish market-data authenticity,
provider acceptance, delivery, or independent population completeness.
It never sends messages, retries, simulates fills, or authorizes orders.
"""

from .forecast_alert_health_audit import audit_forecast_alert_health
from .forecast_delivery_acceptance_audit import audit_forecast_delivery_acceptances

_MAX_ROWS = 1000
_CLAIMED_STATES = {"IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED"}


def reconcile_forecast_claim_receipts(records, claims, receipts, *, as_of):
    """Cross-check decoded outbox states with caller-declared claims/receipts.

    `records` are [{"sessionId": str, "state": ForecastAlertOutbox._unpack(...)}].
    A claimed outbox state must have exactly one matching claim record; queued
    and cancelled states must have none. A self-attested ACK without a recorded
    accepted transport result is a review condition, not delivery evidence.
    A transport acceptance with an uncertain outbox state is also a review
    condition, never permission to resend.
    """
    if type(records) is not list or len(records) > _MAX_ROWS:
        raise ValueError("Invalid bounded forecast claim/outbox population")
    expected_keys = []
    for record in records:
        if (type(record) is not dict or set(record) != {"sessionId", "state"}
                or type(record["state"]) is not dict
                or "forecastId" not in record["state"]):
            raise ValueError("Malformed forecast claim/outbox record")
        expected_keys.append((record["sessionId"], record["state"]["forecastId"]))

    # Both audits validate strict shapes, chronology, bounds, duplicate keys,
    # self-attested provider-result flags and fail-closed authority fields.
    health = audit_forecast_alert_health(records, expected_keys, as_of=as_of)
    acceptance = audit_forecast_delivery_acceptances(claims, receipts, as_of=as_of)

    claimed = {}
    for record in records:
        state = record["state"]
        if state["status"] in _CLAIMED_STATES:
            claimed[(record["sessionId"], state["forecastId"])] = state
    claim_map = {(c["sessionId"], c["forecastId"]): c for c in claims}
    if set(claim_map) != set(claimed):
        raise ValueError("Claim population disagrees with persisted outbox states")
    for key, state in claimed.items():
        claim = claim_map[key]
        if (claim["claimId"] != state["claimId"]
                or claim["claimedAt"] != state["claimedAt"]
                or claim["expiresAt"] != state["expiresAt"]):
            raise ValueError("Claim identity or timestamps disagree with persisted outbox")

    accepted = {(r["sessionId"], r["forecastId"]) for r in receipts}
    ack_without_receipt = sorted(
        key for key, state in claimed.items()
        if state["status"] == "ACK_RECORDED_UNVERIFIED" and key not in accepted)
    acceptance_not_acked = sorted(
        key for key, state in claimed.items()
        if state["status"] == "IN_FLIGHT_UNCERTAIN" and key in accepted)
    unresolved = sorted(
        key for key, state in claimed.items()
        if state["status"] == "IN_FLIGHT_UNCERTAIN" and key not in accepted)
    needs_review = (health["status"] == "OPERATOR_REVIEW_REQUIRED"
                    or acceptance["status"] == "OPERATOR_REVIEW_REQUIRED"
                    or bool(ack_without_receipt or acceptance_not_acked or unresolved))
    status = ("OPERATOR_REVIEW_REQUIRED" if needs_review else
              "NO_CLAIMED_ALERTS" if not claimed else
              "SELF_ATTESTED_CROSS_STORE_ONLY")
    return {
        "status": status,
        "evidence": "DECLARED_OUTBOX_AND_SELF_ATTESTED_TRANSPORT_NOT_INDEPENDENT",
        "outboxCount": len(records),
        "claimedCount": len(claimed),
        "selfAttestedAcceptanceCount": len(accepted),
        "ackWithoutReceiptCount": len(ack_without_receipt),
        "acceptanceNotAckedCount": len(acceptance_not_acked),
        "unresolvedClaimCount": len(unresolved),
        "ackWithoutReceiptKeys": [list(k) for k in ack_without_receipt],
        "acceptanceNotAckedKeys": [list(k) for k in acceptance_not_acked],
        "unresolvedClaimKeys": [list(k) for k in unresolved],
        "outboxHealthStatus": health["status"],
        "acceptanceAuditStatus": acceptance["status"],
        "independentlyComplete": False,
        "providerAcceptanceIndependentlyVerified": False,
        "recipientDeliveryVerified": False,
        "retryPermitted": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
