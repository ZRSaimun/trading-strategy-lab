"""Offline HMAC-bound Telegram forecast-review recipient policy audit.

No sender, secret storage, entitlement, or trading authorization. Caller must
independently establish the verification key's operator-controlled provenance.
"""
import hashlib
import hmac
import json
import re

_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_CHAT = re.compile(r"-?[0-9]{1,20}\Z")
_KEY_ID = re.compile(r"[A-Za-z0-9_-]{1,32}\Z")
_HEX = re.compile(r"[0-9a-f]{64}\Z")
_DOMAIN = b"TradingStrategyLab/forecast-recipient-policy/v1\n"
_MAX_BYTES = 16_384
_MAX_CLAIMS = 1_000
_MAX_RECIPIENTS = 100
_MAX_VALIDITY = 30 * 86_400
_CLAIM_KEYS = {"sessionId", "forecastId", "claimId", "recipientId", "claimedAt", "expiresAt"}
_POLICY_KEYS = {"version", "audience", "validFrom", "validUntil", "recipients", "revocations"}


def _epoch(v):
    return type(v) is int and 0 <= v <= 2**53 - 1


def _strict_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate recipient policy JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite policy number")))


def audit_forecast_recipient_policy(claims, signed_policy, verification_keys, *, as_of):
    """Audit claimed recipients against a separately authenticated policy.

    Signed policy and key provenance must be verified out of band. This audit
    never returns a send permission, chat identifier, or signing key.
    """
    if not _epoch(as_of) or type(claims) is not list or len(claims) > _MAX_CLAIMS:
        raise ValueError("Invalid bounded recipient policy audit population")
    if type(signed_policy) is not dict or set(signed_policy) != {"keyId", "payload", "signature"}:
        raise ValueError("Invalid signed recipient policy envelope")
    key_id, raw, signature = (signed_policy[k] for k in ("keyId", "payload", "signature"))
    if (type(key_id) is not str or not _KEY_ID.fullmatch(key_id)
            or type(raw) is not str or len(raw.encode("utf-8")) > _MAX_BYTES
            or type(signature) is not str or not _HEX.fullmatch(signature)
            or type(verification_keys) is not dict or key_id not in verification_keys):
        raise ValueError("Missing or invalid signed recipient policy")
    key = verification_keys[key_id]
    if type(key) is not bytes or len(key) < 32:
        raise ValueError("Invalid recipient policy verification key")
    expected = hmac.new(key, _DOMAIN + raw.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ValueError("Recipient policy authentication failed")
    try:
        policy = _strict_json(raw)
    except (TypeError, ValueError, RecursionError) as exc:
        raise ValueError("Malformed authenticated recipient policy") from exc
    if (type(policy) is not dict or set(policy) != _POLICY_KEYS
            or json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                          allow_nan=False) != raw
            or type(policy["version"]) is not int or policy["version"] != 1
            or policy["audience"] != "forecast-review-telegram"
            or not _epoch(policy["validFrom"]) or not _epoch(policy["validUntil"])
            or not 0 < policy["validUntil"] - policy["validFrom"] <= _MAX_VALIDITY):
        raise ValueError("Invalid recipient policy scope or validity")
    recipients, revocations = policy["recipients"], policy["revocations"]
    if (type(recipients) is not list or not 1 <= len(recipients) <= _MAX_RECIPIENTS
            or any(type(r) is not str or not _CHAT.fullmatch(r) for r in recipients)
            or len(set(recipients)) != len(recipients)
            or type(revocations) is not list or len(revocations) > _MAX_RECIPIENTS):
        raise ValueError("Invalid recipient policy allowlist")
    revoked = {}
    for row in revocations:
        if (type(row) is not dict or set(row) != {"recipientId", "at"}
                or type(row["recipientId"]) is not str
                or row["recipientId"] not in recipients or row["recipientId"] in revoked
                or not _epoch(row["at"]) or not policy["validFrom"] <= row["at"] < policy["validUntil"]):
            raise ValueError("Invalid recipient policy revocation")
        revoked[row["recipientId"]] = row["at"]
    seen = set()
    unauthorized = 0
    revoked_count = 0
    expired_count = 0
    beyond_policy_expiry_count = 0
    for claim in claims:
        if type(claim) is not dict or set(claim) != _CLAIM_KEYS:
            raise ValueError("Malformed forecast recipient claim")
        session, forecast, claim_id, recipient = (claim[k] for k in
                                                 ("sessionId", "forecastId", "claimId", "recipientId"))
        if (any(type(v) is not str or not _ID.fullmatch(v) for v in (session, forecast))
                or type(claim_id) is not str or not re.fullmatch(r"[0-9a-f]{32}", claim_id)
                or type(recipient) is not str or not _CHAT.fullmatch(recipient)
                or not _epoch(claim["claimedAt"]) or not _epoch(claim["expiresAt"])
                or not claim["claimedAt"] < claim["expiresAt"]
                or claim["claimedAt"] > as_of
                or claim["expiresAt"] - claim["claimedAt"] > 3600):
            raise ValueError("Invalid recipient claim identity or chronology")
        if (session, forecast) in seen or claim_id in seen:
            raise ValueError("Duplicate forecast recipient claim")
        seen.add((session, forecast))
        seen.add(claim_id)
        if claim["expiresAt"] <= as_of:
            expired_count += 1
        if claim["expiresAt"] > policy["validUntil"]:
            beyond_policy_expiry_count += 1
        if (recipient not in recipients or not policy["validFrom"] <= claim["claimedAt"] < policy["validUntil"]):
            unauthorized += 1
        elif recipient in revoked and revoked[recipient] <= as_of:
            revoked_count += 1
    policy_current = policy["validFrom"] <= as_of < policy["validUntil"]
    status = ("OPERATOR_REVIEW_REQUIRED" if (not policy_current or unauthorized or revoked_count
                                              or expired_count or beyond_policy_expiry_count) else
              "NO_CLAIMS" if not claims else "SIGNED_POLICY_MATCH_REVIEW_ONLY")
    return {"status": status, "evidence": "HMAC_POLICY_CALLER_KEY_NOT_INDEPENDENTLY_ANCHORED",
            "declaredClaimCount": len(claims), "unauthorizedClaimCount": unauthorized,
            "revokedRecipientClaimCount": revoked_count, "expiredClaimCount": expired_count,
            "claimExpiryBeyondPolicyCount": beyond_policy_expiry_count,
            "policyCurrent": policy_current,
            "verificationKeyProvenanceVerified": False, "recipientDeliveryVerified": False,
            "retryPermitted": False, "maySendNotification": False,
            "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False}
