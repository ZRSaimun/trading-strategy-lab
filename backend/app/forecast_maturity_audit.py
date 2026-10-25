"""Disconnected, read-only maturity audit for a validated forecast journal snapshot.

This is not a feed authenticator, market-session calendar, notification sender,
trading model, or broker integration. `as_of` is caller supplied and unverified.
"""
from collections import defaultdict
import math

EVIDENCE = "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"
HORIZONS = (1, 3, 12)
FORECAST_FIELDS = {"id", "modelVersion", "horizon", "probability", "baseStart",
                   "baseClose", "issuedAt", "targetStart", "status", "resolvedAt", "outcomeUp"}


def _epoch(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def audit_forecast_maturity(snapshot, *, as_of, grace_seconds=0):
    """Count overdue unresolved forecasts without interpreting session closures as gaps.

    The caller MUST pass an unmodified ForecastEventStore.load snapshot. This
    conservative audit validates linkage and temporal consistency, but cannot
    independently authenticate that the journal or `as_of` came from a server.
    """
    if not _epoch(as_of) or type(grace_seconds) is not int or not 0 <= grace_seconds <= 86400:
        raise ValueError("Invalid maturity audit clock or grace")
    if (type(snapshot) is not dict or set(snapshot) !=
            {"sequence", "identity", "maxLagSeconds", "events", "forecasts", "evidence"}
            or snapshot["evidence"] != EVIDENCE):
        raise ValueError("Expected disconnected forecast journal snapshot")
    identity = snapshot["identity"]
    if (type(identity) is not dict or set(identity) !=
            {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}
            or any(type(identity[k]) is not str or not identity[k] or identity[k] != identity[k].strip()
                   for k in ("instrument", "provider", "venue", "sourceId"))
            or identity["priceSide"] not in ("bid", "ask", "mid")
            or type(identity["priceSide"]) is not str
            or type(identity["seconds"]) is not int
            or not 60 <= identity["seconds"] <= 86400 or identity["seconds"] % 60):
        raise ValueError("Invalid maturity source identity")
    seconds, lag = identity["seconds"], snapshot["maxLagSeconds"]
    events, forecasts = snapshot["events"], snapshot["forecasts"]
    if (type(lag) is not int or not 0 <= lag <= 3600 or type(events) is not list
            or type(forecasts) is not list or len(events) > 5000
            or type(snapshot["sequence"]) is not int or snapshot["sequence"] != len(events)
            or len(forecasts) > len(events)):
        raise ValueError("Invalid maturity journal bounds")
    issued = {}
    last_received = -1
    for seq, event in enumerate(events, 1):
        if (type(event) is not dict or event.get("seq") != seq
                or not _epoch(event.get("receivedAt"))
                or not last_received <= event["receivedAt"] <= as_of):
            raise ValueError("Invalid maturity event order")
        last_received = event["receivedAt"]
        if event.get("kind") == "FORECAST":
            fid = event.get("id")
            if type(fid) is not str or not fid or fid in issued:
                raise ValueError("Duplicate forecast issuance")
            issued[fid] = event
        elif event.get("kind") != "CANDLE":
            raise ValueError("Unexpected journal event")
    if len(issued) != len(forecasts):
        raise ValueError("Forecast issuance count mismatch")
    groups = defaultdict(lambda: {"issued": 0, "settled": 0, "voidGap": 0,
                                  "pendingNotDue": 0, "pendingOverdue": 0})
    seen = set()
    for row in forecasts:
        if type(row) is not dict or set(row) != FORECAST_FIELDS:
            raise ValueError("Invalid maturity forecast row")
        fid, model, horizon, probability = (row[k] for k in ("id", "modelVersion", "horizon", "probability"))
        if (type(fid) is not str or fid in seen or fid not in issued
                or type(model) is not str or not model or type(horizon) is not int
                or horizon not in HORIZONS or type(probability) not in (int, float)
                or not math.isfinite(probability) or not 0 < probability < 1):
            raise ValueError("Invalid maturity forecast identity")
        seen.add(fid)
        event = issued[fid]
        if (event.get("modelVersion") != model or event.get("horizon") != horizon
                or event.get("probability") != probability or event.get("baseStart") != row["baseStart"]
                or event["receivedAt"] != row["issuedAt"]):
            raise ValueError("Maturity issuance mismatch")
        start, target, issued_at = row["baseStart"], row["targetStart"], row["issuedAt"]
        close, status, resolved, outcome = row["baseClose"], row["status"], row["resolvedAt"], row["outcomeUp"]
        if (not all(_epoch(x) for x in (start, target, issued_at))
                or start % seconds or target != start + horizon * seconds
                or not start + seconds <= issued_at < start + 2 * seconds
                or type(close) not in (int, float) or not math.isfinite(close) or close <= 0
                or status not in ("PENDING", "SETTLED", "VOID_GAP")):
            raise ValueError("Invalid maturity forecast timing")
        due = target + seconds + lag + grace_seconds
        if status == "PENDING":
            if resolved is not None or outcome is not None:
                raise ValueError("Pending forecast has an outcome")
            bucket = "pendingOverdue" if as_of >= due else "pendingNotDue"
        elif status == "SETTLED":
            if (type(outcome) is not bool or not _epoch(resolved)
                    or not target + seconds <= resolved <= as_of):
                raise ValueError("Settlement before completed target or audit time")
            bucket = "settled"
        else:
            if outcome is not None or not _epoch(resolved) or not issued_at <= resolved <= as_of:
                raise ValueError("Invalid void-gap resolution")
            bucket = "voidGap"
        group = groups[(model, horizon)]
        group["issued"] += 1
        group[bucket] += 1
    if seen != set(issued):
        raise ValueError("Unmatched forecast issuance")
    rows = []
    for (model, horizon), counts in sorted(groups.items()):
        matured = counts["settled"] + counts["voidGap"] + counts["pendingOverdue"]
        rows.append({"modelVersion": model, "horizonCandles": horizon, **counts,
                     "maturedOrOverdue": matured,
                     "settledFractionOfMatured": counts["settled"] / matured if matured else None,
                     "requiresReconciliation": bool(counts["pendingOverdue"] or counts["voidGap"])})
    return {"evidence": EVIDENCE, "asOfUnverified": as_of,
            "sourceAuthenticated": False, "marketSessionsVerified": False,
            "liveExecutableQuotes": False, "notificationsEnabled": False,
            "paperTradingEnabled": False, "profitabilityEstablished": False,
            "netReturn": None, "maximumDrawdown": None,
            "identity": identity.copy(), "sequence": snapshot["sequence"], "groups": rows,
            "limitations": "Overdue means no journal resolution by caller-supplied as_of; "
                           "market closure, source outage and session calendars are unverified. "
                           "No verified forward returns or execution prices."}
