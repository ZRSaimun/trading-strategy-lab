"""Offline self-attested Telegram acceptance correlation; no HTTP or broker calls."""
import copy

import pytest

from app.forecast_delivery_acceptance_audit import audit_forecast_delivery_acceptances as audit


def claim(session="s1", forecast="f1", cid="a" * 32, recipient="-1001234567890",
          claimed=130, expires=180):
    return {"sessionId": session, "forecastId": forecast, "claimId": cid,
            "recipientId": recipient, "claimedAt": claimed, "expiresAt": expires}


def receipt(c, message_id=55, recorded=140):
    return {"sessionId": c["sessionId"], "forecastId": c["forecastId"],
            "claimId": c["claimId"], "recordedAt": recorded,
            "transportResult": {
                "provider": "telegram", "providerAccepted": True,
                "deliveryVerified": False, "messageId": message_id,
                "recipientId": c["recipientId"], "retryPermitted": False,
                "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False}}


def test_matching_result_is_self_attested_not_delivery_or_order_authority():
    c = claim()
    report = audit([c], [receipt(c)], as_of=150)
    assert report["status"] == "SELF_ATTESTED_ACCEPTANCE_ONLY"
    assert report["recordedAcceptanceCount"] == 1
    assert report["unresolvedClaimCount"] == 0
    assert report["providerAcceptanceIndependentlyVerified"] is False
    assert report["recipientDeliveryVerified"] is False
    assert all(report[k] is False for k in (
        "retryPermitted", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_missing_result_is_uncertain_and_never_retried():
    c = claim()
    report = audit([c], [], as_of=150)
    assert report["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert report["unresolvedKeys"] == [["s1", "f1"]]
    assert report["expiredUnresolvedCount"] == 0
    assert report["retryPermitted"] is False


def test_expired_unresolved_and_late_recording_require_review():
    c = claim()
    missing = audit([c], [], as_of=180)
    assert missing["expiredUnresolvedCount"] == 1
    late = audit([c], [receipt(c, recorded=180)], as_of=190)
    assert late["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert late["lateRecordedKeys"] == [["s1", "f1"]]
    assert late["lateRecordedCount"] == 1


def test_recorded_after_expiry_is_not_claimed_as_late_provider_send():
    c = claim()
    report = audit([c], [receipt(c, recorded=181)], as_of=200)
    assert report["evidence"] == "SELF_ATTESTED_TRANSPORT_RESULTS_NOT_PROVIDER_RECONCILED"
    assert report["providerAcceptanceIndependentlyVerified"] is False


def test_multiple_claims_message_ids_scoped_to_recipient():
    a = claim()
    b = claim(session="s2", forecast="f2", cid="b" * 32, recipient="-1009876543210")
    result = audit([a, b], [receipt(a, 55), receipt(b, 55)], as_of=150)
    assert result["recordedAcceptanceCount"] == 2


def test_duplicate_message_id_same_recipient_fails_closed():
    a = claim()
    b = claim(session="s2", forecast="f2", cid="b" * 32)
    with pytest.raises(ValueError, match="Reused Telegram"):
        audit([a, b], [receipt(a, 55), receipt(b, 55)], as_of=150)


@pytest.mark.parametrize("mutate", [
    lambda c, r: r.update(claimId="b" * 32),
    lambda c, r: r.update(sessionId="unknown"),
    lambda c, r: r.update(recordedAt=129),
    lambda c, r: r.update(recordedAt=151),
    lambda c, r: r["transportResult"].update(recipientId="-1000000000000"),
    lambda c, r: r["transportResult"].update(providerAccepted=1),
    lambda c, r: r["transportResult"].update(deliveryVerified=True),
    lambda c, r: r["transportResult"].update(retryPermitted=True),
    lambda c, r: r["transportResult"].update(mayExecuteLiveOrder=True),
    lambda c, r: r["transportResult"].update(messageId=True),
    lambda c, r: r["transportResult"].update(messageId=0),
    lambda c, r: r["transportResult"].update(provider="other"),
    lambda c, r: r["transportResult"].update(extra="untrusted"),
    lambda c, r: r.update(extra="untrusted"),
])
def test_unregistered_or_malformed_result_rejected(mutate):
    c = claim()
    r = receipt(c)
    mutate(c, r)
    with pytest.raises(ValueError):
        audit([c], [r], as_of=150)


def test_duplicate_claim_receipt_or_claim_id_rejected():
    c = claim()
    with pytest.raises(ValueError, match="Duplicate forecast delivery claim"):
        audit([c, copy.deepcopy(c)], [], as_of=150)
    other = claim(session="s2", forecast="f2")
    with pytest.raises(ValueError, match="Duplicate forecast delivery claim"):
        audit([c, other], [], as_of=150)
    with pytest.raises(ValueError, match="Duplicate, unregistered"):
        audit([c], [receipt(c), receipt(c, 56)], as_of=150)


@pytest.mark.parametrize("bad", [
    lambda c: c.update(claimId="bad"),
    lambda c: c.update(recipientId="@channel"),
    lambda c: c.update(claimedAt=True),
    lambda c: c.update(claimedAt=180),
    lambda c: c.update(expiresAt=130),
    lambda c: c.update(claimedAt=151),
    lambda c: c.update(sessionId="invalid:session"),
    lambda c: c.update(extra=True),
])
def test_malformed_claim_rejected(bad):
    c = claim()
    bad(c)
    with pytest.raises(ValueError):
        audit([c], [], as_of=150)


def test_empty_population_never_green_and_no_mutation():
    assert audit([], [], as_of=150)["status"] == "NO_DECLARED_CLAIMS"
    c = claim()
    r = receipt(c)
    original = copy.deepcopy((c, r))
    audit([c], [r], as_of=150)
    assert (c, r) == original


@pytest.mark.parametrize("clock", [True, -1, 1.2, 2**53])
def test_invalid_clock_rejected(clock):
    with pytest.raises(ValueError, match="clock"):
        audit([], [], as_of=clock)


def test_population_bounds_fail_closed():
    with pytest.raises(ValueError, match="bounded"):
        audit([None] * 1001, [], as_of=150)
    with pytest.raises(ValueError, match="bounded"):
        audit([], [None] * 1001, as_of=150)

@pytest.mark.parametrize("recipient", [
    "0", "-0", "000123", "-00123", "+123", "-4000000000001",
    "1099511627776", "111111111111111111111",
])
def test_claim_rejects_recipient_transport_cannot_send(recipient):
    with pytest.raises(ValueError, match="identity or chronology"):
        audit([claim(recipient=recipient)], [], as_of=150)


def test_canonical_telegram_chat_id_range_boundaries_match_sender():
    a = claim(recipient="-4000000000000")
    b = claim(session="s2", forecast="f2", cid="b" * 32,
              recipient="1099511627775")
    report = audit([a, b], [receipt(a), receipt(b)], as_of=150)
    assert report["recordedAcceptanceCount"] == 2
    assert report["maySendNotification"] is False
