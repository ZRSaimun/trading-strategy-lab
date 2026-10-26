"""Offline paired Brier audit against a *declared*, pre-window frozen benchmark.

No source authentication, preregistration proof, notification, order, fill or
trading permission. This function never promotes journal observations to live.
"""
import math

_EVIDENCE = "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"
_IDENTITY_KEYS = {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}
_FORECAST_KEYS = {"id", "modelVersion", "horizon", "probability", "baseStart",
                  "baseClose", "issuedAt", "targetStart", "status", "resolvedAt", "outcomeUp"}
_BASELINE_KEYS = {"baselineId", "modelVersion", "horizonCandles", "baselineProbability", "frozenAt"}


def _epoch(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _prob(value):
    return type(value) in (int, float) and math.isfinite(value) and 0 < value < 1


def audit_frozen_baseline(snapshot, baseline, *, window_start, window_end, as_of,
                          min_settled=30):
    """Score every matching issuance in a predeclared [start,end) window.

    Pending, void, or as-of-unresolved records suppress *all* skill metrics;
    filtering them out would select outcomes. Source and freeze declarations are
    NOT independently authenticated. The caller must supply a validated journal
    snapshot; issuance rows are also cross-checked against its forecast events.
    """
    if (type(min_settled) is not int or not 30 <= min_settled <= 5000
            or not all(_epoch(v) for v in (window_start, window_end, as_of))
            or not window_start < window_end <= as_of):
        raise ValueError("Invalid predeclared evaluation window")
    if (type(baseline) is not dict or set(baseline) != _BASELINE_KEYS
            or type(baseline["baselineId"]) is not str
            or not 1 <= len(baseline["baselineId"]) <= 120
            or baseline["baselineId"] != baseline["baselineId"].strip()
            or type(baseline["modelVersion"]) is not str
            or not 1 <= len(baseline["modelVersion"]) <= 120
            or baseline["modelVersion"] != baseline["modelVersion"].strip()
            or type(baseline["horizonCandles"]) is not int
            or baseline["horizonCandles"] not in (1, 3, 12)
            or not _prob(baseline["baselineProbability"])
            or not _epoch(baseline["frozenAt"])
            or baseline["frozenAt"] >= window_start):
        raise ValueError("Benchmark must be declared before evaluation starts")
    if (type(snapshot) is not dict or set(snapshot) !=
            {"sequence", "identity", "maxLagSeconds", "events", "forecasts", "evidence"}
            or snapshot["evidence"] != _EVIDENCE):
        raise ValueError("Expected disconnected journal snapshot")
    identity = snapshot["identity"]
    if (type(identity) is not dict or set(identity) != _IDENTITY_KEYS
            or type(identity["seconds"]) is not int
            or not 60 <= identity["seconds"] <= 86400
            or identity["seconds"] % 60
            or type(identity["priceSide"]) is not str
            or identity["priceSide"] not in ("bid", "ask", "mid")
            or any(type(identity[k]) is not str or not identity[k] or
                   identity[k] != identity[k].strip() for k in
                   ("instrument", "provider", "venue", "sourceId"))):
        raise ValueError("Invalid feed identity")
    events, forecasts = snapshot["events"], snapshot["forecasts"]
    if (type(events) is not list or type(forecasts) is not list
            or len(events) > 5000 or len(forecasts) > len(events)
            or type(snapshot["sequence"]) is not int
            or snapshot["sequence"] != len(events)
            or type(snapshot["maxLagSeconds"]) is not int
            or not 0 <= snapshot["maxLagSeconds"] <= 3600):
        raise ValueError("Invalid journal census")
    issuance = {}
    for i, event in enumerate(events, 1):
        if (type(event) is not dict or event.get("seq") != i
                or not _epoch(event.get("receivedAt"))):
            raise ValueError("Malformed event sequence")
        if event.get("kind") == "FORECAST":
            fid = event.get("id")
            if type(fid) is not str or not fid or fid in issuance:
                raise ValueError("Duplicate or malformed issuance")
            issuance[fid] = event
    if len(issuance) != len(forecasts):
        raise ValueError("Issuance/forecast census mismatch")
    seen = set()
    selected = []
    for row in forecasts:
        if type(row) is not dict or set(row) != _FORECAST_KEYS:
            raise ValueError("Malformed forecast row")
        fid = row["id"]
        if type(fid) is not str or fid in seen or fid not in issuance:
            raise ValueError("Unmatched forecast issuance")
        seen.add(fid)
        event = issuance[fid]
        if (event.get("kind") != "FORECAST" or event.get("modelVersion") != row["modelVersion"]
                or event.get("horizon") != row["horizon"]
                or event.get("probability") != row["probability"]
                or event.get("baseStart") != row["baseStart"]
                or event.get("receivedAt") != row["issuedAt"]
                or type(row["modelVersion"]) is not str or not row["modelVersion"]
                or type(row["horizon"]) is not int or row["horizon"] not in (1, 3, 12)
                or not _prob(row["probability"])
                or not all(_epoch(row[k]) for k in ("baseStart", "issuedAt", "targetStart"))
                or row["targetStart"] != row["baseStart"] + row["horizon"] * identity["seconds"]
                or not row["baseStart"] + identity["seconds"] <= row["issuedAt"] < row["baseStart"] + 2 * identity["seconds"]
                or type(row["baseClose"]) not in (int, float)
                or not math.isfinite(row["baseClose"]) or row["baseClose"] <= 0
                or row["status"] not in ("SETTLED", "PENDING", "VOID_GAP")
                or (row["status"] == "SETTLED" and
                    (type(row["outcomeUp"]) is not bool or not _epoch(row["resolvedAt"])
                     or row["resolvedAt"] < row["targetStart"] + identity["seconds"]))
                or (row["status"] == "PENDING" and
                    (row["outcomeUp"] is not None or row["resolvedAt"] is not None))
                or (row["status"] == "VOID_GAP" and
                    (row["outcomeUp"] is not None or not _epoch(row["resolvedAt"])
                     or row["resolvedAt"] < row["issuedAt"]))):
            raise ValueError("Inconsistent journal forecast")
        if (row["modelVersion"] == baseline["modelVersion"]
                and row["horizon"] == baseline["horizonCandles"]
                and window_start <= row["issuedAt"] < window_end):
            selected.append(row)
    if seen != set(issuance):
        raise ValueError("Missing journal forecast")
    selected.sort(key=lambda row: (row["issuedAt"], row["id"]))
    pending = sum(row["status"] == "PENDING" for row in selected)
    void = sum(row["status"] == "VOID_GAP" for row in selected)
    late = sum(row["status"] == "SETTLED" and row["resolvedAt"] > as_of for row in selected)
    immature = sum(row["targetStart"] + identity["seconds"] > as_of for row in selected)
    settled = sum(row["status"] == "SETTLED" and row["resolvedAt"] <= as_of for row in selected)
    status = ("WITHHELD_CENSORED" if pending or void or late or immature
              else "INSUFFICIENT_SAMPLE" if settled < min_settled
              else "DESCRIPTIVE_ONLY")
    result = {"status": status, "evidence": "SELF_DECLARED_FROZEN_BENCHMARK_UNVERIFIED_SOURCE",
              "identity": identity.copy(), "baselineId": baseline["baselineId"],
              "modelVersion": baseline["modelVersion"], "horizonCandles": baseline["horizonCandles"],
              "windowStart": window_start, "windowEnd": window_end, "asOf": as_of,
              "issued": len(selected), "settledAsOf": settled, "pending": pending,
              "voidGap": void, "settledAfterAsOf": late, "notMatureAsOf": immature,
              "minimumSettled": min_settled, "modelBrier": None, "baselineBrier": None,
              "brierSkill": None, "meanPairedExcessLoss": None,
              "worstPairedExcessLoss": None, "maxCumulativeExcessLoss": None,
              "sourceAuthenticated": False, "baselineFreezeExternallyVerified": False,
              "statisticalSignificanceEstablished": False, "forwardReturnsVerified": False,
              "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False,
              "netReturn": None, "maximumTradingDrawdown": None}
    if status != "DESCRIPTIVE_ONLY":
        return result
    base_p = baseline["baselineProbability"]
    model_losses, base_losses, deltas = [], [], []
    for row in selected:
        y = int(row["outcomeUp"])
        m, b = (row["probability"] - y) ** 2, (base_p - y) ** 2
        model_losses.append(m)
        base_losses.append(b)
        deltas.append(m - b)
    n = len(deltas)
    model_brier, baseline_brier = sum(model_losses) / n, sum(base_losses) / n
    cumulative = peak_excess = 0.0
    for delta in deltas:
        cumulative += delta
        peak_excess = max(peak_excess, cumulative)
    result.update(modelBrier=model_brier, baselineBrier=baseline_brier,
                  brierSkill=1 - model_brier / baseline_brier,
                  meanPairedExcessLoss=sum(deltas) / n,
                  worstPairedExcessLoss=max(deltas),
                  maxCumulativeExcessLoss=peak_excess)
    return result
