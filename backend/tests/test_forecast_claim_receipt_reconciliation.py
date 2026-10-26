"""Cross-store forecast claim/receipt safety tests; synthetic, no HTTP."""
import copy

import pytest

from app.forecast_claim_receipt_reconciliation import reconcile_forecast_claim_receipts as audit


IDENTITY = {"instrument": "XAUUSD", "provider": "synthetic", "venue": "test",
            "sourceId": "fake", "priceSide": "bid", "seconds": 60}


def state(status="ACK_RECORDED_UNVERIFIED", cid="a" * 32):
    claimed = status in ("IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED")
    return {"version": 1, "identity": IDENTITY.copy(), "forecastId": "f1",
            "modelVersion": "m1", "horizon": 1, "baseStart": 60, "issueSeq": 2,
            "issuedAt": 130, "expiresAt": 180, "status": status,
            "claimId": cid if claimed else None,
            "claimedAt": 135 if claimed else None,
            "ackAt": 139 if status == "ACK_RECORDED_UNVERIFIED" else None}


def row(s=None, session="s1"):
    return {"sessionId": session, "state": state() if s is None else s}


def claim():
    return {"sessionId": "s1", "forecastId": "f1", "claimId": "a" * 32,
            "recipientId": "-1001234567890", "claimedAt": 135, "expiresAt": 180}


def receipt():
    return {"sessionId": "s1", "forecastId": "f1", "claimId": "a" * 32,
            "recordedAt": 138, "transportResult": {
                "provider": "telegram", "providerAccepted": True,
                "deliveryVerified": False, "messageId": 42,
                "recipientId": "-1001234567890", "retryPermitted": False,
                "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False}}


def test_matching_ack_is_only_self_attested():
    report = audit([row()], [claim()], [receipt()], as_of=140)
    assert report["status"] == "SELF_ATTESTED_CROSS_STORE_ONLY"
    assert report["claimedCount"] == 1
    assert report["selfAttestedAcceptanceCount"] == 1
    assert report["ackWithoutReceiptCount"] == 0
    assert report["independentlyComplete"] is False
    assert all(report[k] is False for k in (
        "providerAcceptanceIndependentlyVerified", "recipientDeliveryVerified",
        "retryPermitted", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_ack_without_receipt_requires_operator_review():
    report = audit([row()], [claim()], [], as_of=140)
    assert report["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert report["ackWithoutReceiptKeys"] == [["s1", "f1"]]


def test_acceptance_without_ack_requires_review_no_retry():
    report = audit([row(state("IN_FLIGHT_UNCERTAIN"))], [claim()],
                   [receipt()], as_of=140)
    assert report["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert report["acceptanceNotAckedKeys"] == [["s1", "f1"]]
    assert report["retryPermitted"] is False


def test_uncertain_missing_receipt_requires_review():
    report = audit([row(state("IN_FLIGHT_UNCERTAIN"))], [claim()], [], as_of=140)
    assert report["unresolvedClaimKeys"] == [["s1", "f1"]]
    assert report["status"] == "OPERATOR_REVIEW_REQUIRED"


@pytest.mark.parametrize("status", ["QUEUED", "CANCELLED"])
def test_unclaimed_alerts_cannot_have_claims(status):
    with pytest.raises(ValueError, match="Claim population"):
        audit([row(state(status))], [claim()], [], as_of=140)


@pytest.mark.parametrize("status", ["QUEUED", "CANCELLED"])
def test_unclaimed_alerts_without_claims_are_not_delivery_evidence(status):
    report = audit([row(state(status))], [], [], as_of=140)
    assert report["status"] == "NO_CLAIMED_ALERTS"
    assert report["selfAttestedAcceptanceCount"] == 0


def test_empty_population_is_not_positive_delivery():
    report = audit([], [], [], as_of=140)
    assert report["status"] == "NO_CLAIMED_ALERTS"
    assert report["independentlyComplete"] is False


def test_missing_claim_for_claimed_outbox_fails_closed():
    with pytest.raises(ValueError, match="Claim population"):
        audit([row()], [], [], as_of=140)


@pytest.mark.parametrize("field,bad", [
    ("claimId", "b" * 32),
    ("claimedAt", 136),
    ("expiresAt", 179),
])
def test_claim_outbox_mismatch_fails_closed(field, bad):
    c = claim()
    c[field] = bad
    with pytest.raises(ValueError, match="disagree"):
        audit([row()], [c], [], as_of=140)


def test_duplicate_outbox_record_rejected():
    with pytest.raises(ValueError):
        audit([row(), row()], [claim()], [receipt()], as_of=140)


def test_unregistered_receipt_rejected():
    with pytest.raises(ValueError):
        audit([], [], [receipt()], as_of=140)


def test_forged_provider_delivery_rejected():
    r = receipt()
    r["transportResult"]["deliveryVerified"] = True
    with pytest.raises(ValueError):
        audit([row()], [claim()], [r], as_of=140)


def test_invalid_outbox_state_rejected():
    s = state()
    s["ackAt"] = 134
    with pytest.raises(ValueError):
        audit([row(s)], [claim()], [receipt()], as_of=140)


def test_bounded_outbox_population_rejected():
    with pytest.raises(ValueError, match="bounded"):
        audit([None] * 1001, [], [], as_of=140)


def test_source_records_are_not_mutated():
    records, claims, receipts = [row()], [claim()], [receipt()]
    before = copy.deepcopy((records, claims, receipts))
    audit(records, claims, receipts, as_of=140)
    assert (records, claims, receipts) == before


def test_expiring_queued_alert_propagates_operator_review():
    report = audit([row(state("QUEUED"))], [], [], as_of=160)
    assert report["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert report["outboxHealthStatus"] == "OPERATOR_REVIEW_REQUIRED"
