"""Offline fail-closed comparison of a declared expected-bar register to a journal.

The register and journal are caller-supplied and UNAUTHENTICATED. This pure
function never permits alerts, fills, or orders. Session breaks are represented
by omitted expected starts; the caller must independently verify that schedule.
"""

import math

_MAX_BARS = 5000
_MAX_EPOCH = 2**53 - 1
_FEED = {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}


def _epoch(value):
    return type(value) is int and 0 <= value <= _MAX_EPOCH


def audit_expected_completed_bars(snapshot, expected_identity, expected_starts, *, as_of):
    """Reject missing/extra/duplicate or prematurely timestamped completed bars.

    expected_starts must be an externally registered, ordered, session-aware
    list of expected completed candle starts, not derived from the journal.
    Neither that independence nor provider authenticity is proven here.
    """
    if not _epoch(as_of):
        raise ValueError("Invalid expected-bar audit time")
    if type(expected_identity) is not dict or set(expected_identity) != _FEED:
        raise ValueError("Invalid expected-bar source identity")
    for field in ("instrument", "provider", "venue", "sourceId"):
        value = expected_identity[field]
        if type(value) is not str or not 1 <= len(value) <= 160 or value != value.strip():
            raise ValueError("Invalid expected-bar source identity")
    if type(expected_identity["priceSide"]) is not str or expected_identity["priceSide"] not in ("bid", "ask", "mid"):
        raise ValueError("Invalid expected-bar quote side")
    seconds = expected_identity["seconds"]
    if type(seconds) is not int or not 60 <= seconds <= 86400 or seconds % 60:
        raise ValueError("Invalid expected-bar duration")
    if (type(expected_starts) is not list or not 1 <= len(expected_starts) <= _MAX_BARS
            or type(snapshot) is not dict
            or snapshot.get("evidence") != "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"
            or snapshot.get("identity") != expected_identity
            or type(snapshot.get("events")) is not list
            or len(snapshot["events"]) > _MAX_BARS):
        raise ValueError("Invalid expected-bar register or journal")
    previous = -1
    for start in expected_starts:
        if not _epoch(start) or start % seconds or start <= previous or start + seconds > as_of:
            raise ValueError("Invalid expected-bar chronology or incomplete candle")
        previous = start
    seen = []
    previous_receipt = -1
    for event in snapshot["events"]:
        if type(event) is not dict:
            raise ValueError("Malformed expected-bar journal event")
        if event.get("kind") != "CANDLE":
            continue
        if set(event) != {"kind", "seq", "receivedAt", "start", "close"}:
            raise ValueError("Malformed completed-candle event")
        start, receipt, close = event["start"], event["receivedAt"], event["close"]
        if (type(close) not in (int, float) or not math.isfinite(close) or close <= 0
                or not _epoch(start)
                or start % seconds or not _epoch(receipt)
                or receipt < start + seconds or receipt > as_of
                or receipt < previous_receipt):
            raise ValueError("Invalid completed-candle receipt chronology")
        previous_receipt = receipt
        seen.append(start)
        if len(seen) > _MAX_BARS:
            raise ValueError("Expected-bar journal limit exceeded")
    if len(seen) != len(set(seen)):
        raise ValueError("Duplicate completed-candle start")
    missing = sorted(set(expected_starts) - set(seen))
    extra = sorted(set(seen) - set(expected_starts))
    if missing or extra:
        raise ValueError("Incomplete or undeclared completed-candle population")
    if seen != expected_starts:
        raise ValueError("Out-of-order completed-candle population")
    return {"status": "DECLARED_MATCH_UNVERIFIED",
            "evidence": "CALLER_DECLARED_REGISTER_NOT_INDEPENDENTLY_ATTESTED",
            "declaredExpectedBarCount": len(expected_starts),
            "journalCompletedBarCount": len(seen),
            "independentlyComplete": False,
            "providerAuthenticated": False,
            "sessionCalendarAuthenticated": False,
            "maySendNotification": False,
            "mayExecutePaperOrder": False,
            "mayExecuteLiveOrder": False}
