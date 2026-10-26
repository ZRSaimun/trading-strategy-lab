"""Synthetic, disconnected recipient policy verification regressions."""
import copy
import hashlib
import hmac
import json

import pytest

from app.forecast_recipient_policy import audit_forecast_recipient_policy, _DOMAIN

KEY = b"synthetic-test-key-32-bytes-long-12345"
KEYS = {"operator-1": KEY}


def policy(**changes):
    body = {"version": 1, "audience": "forecast-review-telegram", "validFrom": 100,
            "validUntil": 1000, "recipients": ["123", "-999"], "revocations": []}
    body.update(changes)
    raw = json.dumps(body, sort_keys=True, separators=(",", ":"))
    return {"keyId": "operator-1", "payload": raw,
            "signature": hmac.new(KEY, _DOMAIN + raw.encode(), hashlib.sha256).hexdigest()}


def claim(**changes):
    row = {"sessionId": "s1", "forecastId": "f1", "claimId": "a" * 32,
           "recipientId": "123", "claimedAt": 130, "expiresAt": 160}
    row.update(changes)
    return row


def audit(rows=None, signed=None, now=140, keys=None):
    return audit_forecast_recipient_policy([claim()] if rows is None else rows,
                                           policy() if signed is None else signed,
                                           KEYS if keys is None else keys, as_of=now)


def test_valid_signed_allowlist_is_review_only():
    result = audit()
    assert result["status"] == "SIGNED_POLICY_MATCH_REVIEW_ONLY"
    assert result["maySendNotification"] is False
    assert result["mayExecuteLiveOrder"] is False
    assert result["verificationKeyProvenanceVerified"] is False
    assert "123" not in repr(result)


def test_empty_population_not_green():
    assert audit([])["status"] == "NO_CLAIMS"


@pytest.mark.parametrize("change", [
    {"recipients": []}, {"recipients": ["123", "123"]},
    {"recipients": ["123", "bad-chat"]},
    {"validFrom": 1000}, {"validUntil": 100 + 31 * 86400},
    {"version": True}, {"audience": "live-order"},
    {"revocations": [{"recipientId": "777", "at": 200}]},
    {"revocations": [{"recipientId": "123", "at": 90}]},
    {"revocations": [{"recipientId": "123", "at": 200}] * 2},
])
def test_malformed_authenticated_policy_fails_closed(change):
    with pytest.raises(ValueError):
        audit(signed=policy(**change))


def test_unsigned_mutation_rejected():
    p = policy()
    p["payload"] = p["payload"].replace("123", "456")
    with pytest.raises(ValueError, match="authentication"):
        audit(signed=p)


def test_wrong_key_and_short_key_rejected():
    for keys in ({"operator-1": b"z" * 32}, {"operator-1": b"short"}, {}):
        with pytest.raises(ValueError):
            audit(keys=keys)


def test_unauthorized_and_claim_outside_policy_are_review_only():
    assert audit([claim(recipientId="444")])["unauthorizedClaimCount"] == 1
    assert audit([claim(claimedAt=80)])["status"] == "OPERATOR_REVIEW_REQUIRED"


def test_revocation_blocks_even_previous_claim_at_review_time():
    p = policy(revocations=[{"recipientId": "123", "at": 200}])
    assert audit(signed=p, now=140)["status"] == "SIGNED_POLICY_MATCH_REVIEW_ONLY"
    assert audit(signed=p, now=200)["revokedRecipientClaimCount"] == 1


def test_policy_expiry_and_not_yet_valid_are_review_only():
    assert audit(now=1000)["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert audit([], now=90)["status"] == "OPERATOR_REVIEW_REQUIRED"


@pytest.mark.parametrize("change", [
    {"claimedAt": True}, {"expiresAt": 130}, {"claimedAt": 200},
    {"claimId": "x" * 32}, {"recipientId": "not-chat"},
    {"sessionId": "bad space"},
])
def test_invalid_claim_fails_closed(change):
    with pytest.raises(ValueError):
        audit([claim(**change)])


def test_duplicate_claim_id_and_forecast_rejected():
    for duplicate in (claim(), claim(forecastId="f2")):
        with pytest.raises(ValueError, match="Duplicate"):
            audit([claim(), duplicate])


def test_rejects_duplicate_json_keys_even_with_valid_signature():
    p = policy()
    raw = p["payload"].replace('"version":1', '"version":1,"version":1')
    p["payload"] = raw
    p["signature"] = hmac.new(KEY, _DOMAIN + raw.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(ValueError):
        audit(signed=p)


def test_noncanonical_json_rejected_even_if_signed():
    p = policy()
    raw = json.dumps(json.loads(p["payload"]), indent=2)
    p["payload"] = raw
    p["signature"] = hmac.new(KEY, _DOMAIN + raw.encode(), hashlib.sha256).hexdigest()
    with pytest.raises(ValueError):
        audit(signed=p)


def test_inputs_not_mutated():
    rows, p, keys = [claim()], policy(), dict(KEYS)
    before = copy.deepcopy((rows, p, keys))
    audit(rows, p, keys=keys)
    assert (rows, p, keys) == before


def test_limits_and_wrong_types_fail_closed():
    for rows in ([claim()] * 1001, "not-a-list"):
        with pytest.raises(ValueError):
            audit(rows)
    with pytest.raises(ValueError):
        audit(now=True)
    p = policy()
    p["signature"] = "0" * 64
    with pytest.raises(ValueError):
        audit(signed=p)


def test_expired_claim_requires_review_at_exclusive_expiry_boundary():
    assert audit(now=159)["status"] == "SIGNED_POLICY_MATCH_REVIEW_ONLY"
    result = audit(now=160)
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["expiredClaimCount"] == 1
    assert result["claimExpiryBeyondPolicyCount"] == 0
    assert result["maySendNotification"] is False


def test_claim_cannot_extend_authorization_past_signed_policy_window():
    result = audit([claim(claimedAt=990, expiresAt=1010)], now=995)
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["claimExpiryBeyondPolicyCount"] == 1
    assert result["expiredClaimCount"] == 0
    assert result["maySendNotification"] is False


def test_claim_max_lifetime_matches_outbox_budget():
    with pytest.raises(ValueError, match="chronology"):
        audit([claim(expiresAt=3731)])
    result = audit([claim(expiresAt=3730)], now=140)
    assert result["claimExpiryBeyondPolicyCount"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"


def test_expiry_violations_are_counted_independently_of_allowlist():
    result = audit([claim(recipientId="444", expiresAt=160)], now=160)
    assert result["unauthorizedClaimCount"] == 1
    assert result["expiredClaimCount"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
