"""Offline correlation of one-attempt Telegram acceptance with forecast claims.

This is a caller-declared, self-attested review. It does not query Telegram,
prove provider/device delivery, permit retries, or authorize trading.
"""
import re

from .forecast_telegram_chat_id import valid_telegram_chat_id

_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_CLAIM = re.compile(r"[0-9a-f]{32}\Z")
_MAX_ROWS = 1000
_CLAIM_FIELDS = {"sessionId", "forecastId", "claimId", "recipientId",
                 "claimedAt", "expiresAt"}
_RECEIPT_FIELDS = {"sessionId", "forecastId", "claimId", "recordedAt",
                   "transportResult"}
_RESULT_FIELDS = {"provider", "providerAccepted", "deliveryVerified", "messageId",
                  "recipientId", "retryPermitted", "mayExecutePaperOrder",
                  "mayExecuteLiveOrder"}


def _epoch(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _valid_id(value, pattern):
    return type(value) is str and pattern.fullmatch(value) is not None


def audit_forecast_delivery_acceptances(claims, receipts, *, as_of):
    """Correlate declared claim identities with self-attested send results.

    Missing results remain uncertain, never a reason to retry. A result is
    recorded *after* the send attempt; recordedAt is NOT provider send time.
    Provider acceptance is not independently confirmed by this audit.
    """
    if not _epoch(as_of):
        raise ValueError("Invalid delivery audit clock")
    if (type(claims) is not list or type(receipts) is not list or
            len(claims) > _MAX_ROWS or len(receipts) > _MAX_ROWS):
        raise ValueError("Invalid bounded delivery audit population")
    expected = {}
    claim_ids = set()
    for claim in claims:
        if type(claim) is not dict or set(claim) != _CLAIM_FIELDS:
            raise ValueError("Malformed forecast delivery claim")
        session, forecast, cid = (claim[k] for k in
                                  ("sessionId", "forecastId", "claimId"))
        if (not _valid_id(session, _ID) or not _valid_id(forecast, _ID) or
                not _valid_id(cid, _CLAIM) or
                not valid_telegram_chat_id(claim["recipientId"]) or
                not _epoch(claim["claimedAt"]) or
                not _epoch(claim["expiresAt"]) or
                not claim["claimedAt"] < claim["expiresAt"] or
                claim["claimedAt"] > as_of):
            raise ValueError("Invalid forecast delivery claim identity or chronology")
        key = (session, forecast)
        if key in expected or cid in claim_ids:
            raise ValueError("Duplicate forecast delivery claim")
        expected[key] = claim
        claim_ids.add(cid)

    seen = set()
    provider_messages = set()
    late = []
    for receipt in receipts:
        if type(receipt) is not dict or set(receipt) != _RECEIPT_FIELDS:
            raise ValueError("Malformed forecast delivery receipt")
        session, forecast, cid = (receipt[k] for k in
                                  ("sessionId", "forecastId", "claimId"))
        if not _valid_id(session, _ID) or not _valid_id(forecast, _ID):
            raise ValueError("Invalid forecast delivery receipt identity")
        key = (session, forecast)
        claim = expected.get(key)
        if claim is None or key in seen or cid != claim["claimId"]:
            raise ValueError("Duplicate, unregistered or mismatched delivery receipt")
        recorded = receipt["recordedAt"]
        if not _epoch(recorded) or not claim["claimedAt"] <= recorded <= as_of:
            raise ValueError("Invalid forecast delivery receipt chronology")
        result = receipt["transportResult"]
        if type(result) is not dict or set(result) != _RESULT_FIELDS:
            raise ValueError("Malformed forecast transport acceptance")
        if (result["provider"] != "telegram" or
                result["providerAccepted"] is not True or
                result["deliveryVerified"] is not False or
                result["retryPermitted"] is not False or
                result["mayExecutePaperOrder"] is not False or
                result["mayExecuteLiveOrder"] is not False or
                type(result["messageId"]) is not int or result["messageId"] <= 0 or
                result["messageId"] > 2**53 - 1 or
                type(result["recipientId"]) is not str or
                result["recipientId"] != claim["recipientId"]):
            raise ValueError("Invalid or mismatched forecast transport result")
        # Telegram message IDs are chat-scoped, not globally unique.
        provider_key = (result["recipientId"], result["messageId"])
        if provider_key in provider_messages:
            raise ValueError("Reused Telegram message identity")
        provider_messages.add(provider_key)
        seen.add(key)
        if recorded >= claim["expiresAt"]:
            late.append(key)

    unresolved = sorted(set(expected) - seen)
    expired = [key for key in unresolved if as_of >= expected[key]["expiresAt"]]
    return {
        "status": ("NO_DECLARED_CLAIMS" if not expected else
                   "OPERATOR_REVIEW_REQUIRED" if unresolved or late else
                   "SELF_ATTESTED_ACCEPTANCE_ONLY"),
        "evidence": "SELF_ATTESTED_TRANSPORT_RESULTS_NOT_PROVIDER_RECONCILED",
        "declaredClaimCount": len(expected),
        "recordedAcceptanceCount": len(seen),
        "unresolvedClaimCount": len(unresolved),
        "expiredUnresolvedCount": len(expired),
        "lateRecordedCount": len(late),
        "unresolvedKeys": [list(k) for k in unresolved],
        "lateRecordedKeys": [list(k) for k in sorted(late)],
        "providerAcceptanceIndependentlyVerified": False,
        "recipientDeliveryVerified": False,
        "retryPermitted": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
