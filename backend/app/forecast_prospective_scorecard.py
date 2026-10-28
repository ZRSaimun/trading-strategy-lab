"""Read-only accountability for a *validated* ForecastEventStore.load snapshot.

This module does not authenticate data, run a model, deliver an alert, simulate
fills, or make trading decisions. Never treat its metrics as trading returns.
"""
import math
from collections import defaultdict

_HORIZONS = (1, 3, 12)
_STATUSES = ("SETTLED", "PENDING", "VOID_GAP")
_REQUIRED = {"sequence", "identity", "maxLagSeconds", "events", "forecasts", "evidence"}
_FORECAST_FIELDS = {"id", "modelVersion", "horizon", "probability", "baseStart",
                    "baseClose", "issuedAt", "targetStart", "status", "resolvedAt", "outcomeUp"}
_EVIDENCE = "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"


def _wilson(successes, count):
    """Descriptive 95% Wilson interval; independence is NOT established."""
    z = 1.959963984540054
    rate = successes / count
    denom = 1 + z * z / count
    centre = (rate + z * z / (2 * count)) / denom
    radius = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denom
    return [max(0.0, centre - radius), min(1.0, centre + radius)]


def summarize_forecast_snapshot(snapshot, *, min_settled=30, calibration_bins=10):
    """Summarize source-isolated prospective *journal records*, not verified feeds.

    Call only on ForecastEventStore.load output. It validates stored replay and
    source isolation; this function additionally fails closed on inconsistent
    outcome/status fields. Missing/void/pending cases remain in the denominator.
    Scores are withheld below min_settled and cannot be interpreted as an edge.
    """
    if type(min_settled) is not int or not 30 <= min_settled <= 5000:
        raise ValueError("Invalid minimum settled sample")
    if type(calibration_bins) is not int or not 2 <= calibration_bins <= 20:
        raise ValueError("Invalid calibration bin count")
    if type(snapshot) is not dict or set(snapshot) != _REQUIRED or snapshot["evidence"] != _EVIDENCE:
        raise ValueError("Expected validated disconnected forecast journal snapshot")
    events, forecasts, identity = snapshot["events"], snapshot["forecasts"], snapshot["identity"]
    lag = snapshot["maxLagSeconds"]
    if type(lag) is not int or not 0 <= lag <= 3600:
        raise ValueError("Invalid forecast scorecard maximum receipt lag")
    if (type(events) is not list or type(forecasts) is not list or len(events) > 5000
            or len(forecasts) > len(events) or type(snapshot["sequence"]) is not int
            or snapshot["sequence"] != len(events) or type(identity) is not dict
            or set(identity) != {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}
            or type(identity["seconds"]) is not int or not 60 <= identity["seconds"] <= 86400
            or identity["seconds"] % 60 or type(identity["priceSide"]) is not str
            or identity["priceSide"] not in ("bid", "ask", "mid")
            or any(type(identity[k]) is not str or not identity[k] or identity[k] != identity[k].strip()
                   for k in ("instrument", "provider", "venue", "sourceId"))):
        raise ValueError("Invalid forecast scorecard identity or sequence")
    forecast_events = {}
    for event in events:
        if type(event) is not dict:
            raise ValueError("Malformed forecast event")
        if event.get("kind") == "FORECAST":
            fid = event.get("id")
            if type(fid) is not str or fid in forecast_events:
                raise ValueError("Duplicate or malformed forecast event")
            forecast_events[fid] = event
    if len(forecast_events) != len(forecasts):
        raise ValueError("Forecast event/outcome count mismatch")

    grouped = defaultdict(list)
    seen = set()
    for row in forecasts:
        if type(row) is not dict or set(row) != _FORECAST_FIELDS:
            raise ValueError("Malformed forecast outcome")
        fid, model, horizon, p = (row[k] for k in ("id", "modelVersion", "horizon", "probability"))
        if (type(fid) is not str or fid in seen or type(model) is not str or not model
                or type(horizon) is not int or horizon not in _HORIZONS
                or type(p) not in (int, float) or not math.isfinite(p) or not 0 < p < 1):
            raise ValueError("Invalid forecast probability or identity")
        seen.add(fid)
        event = forecast_events.get(fid)
        if (event is None or event.get("modelVersion") != model or event.get("horizon") != horizon
                or event.get("probability") != p or event.get("baseStart") != row["baseStart"]
                or event.get("receivedAt") != row["issuedAt"]):
            raise ValueError("Forecast issuance/outcome mismatch")
        status, outcome, resolved = row["status"], row["outcomeUp"], row["resolvedAt"]
        base, issued, target = row["baseStart"], row["issuedAt"], row["targetStart"]
        seconds = identity["seconds"]
        # Mirror the journal's completed-candle issuance window. A scorecard
        # must not turn a caller-forged early/stale forecast into a valid score.
        if (type(status) is not str or status not in _STATUSES
                or type(base) is not int or not 0 <= base <= 2**53 - 1
                or base % seconds or type(issued) is not int
                or not base + seconds <= issued < base + 2 * seconds
                or issued - (base + seconds) > lag
                or type(target) is not int or target != base + horizon * seconds
                or target + seconds > 2**53 - 1
                or type(row["baseClose"]) not in (int, float)
                or not math.isfinite(row["baseClose"]) or row["baseClose"] <= 0
                # A settled target label cannot be observed before its candle closes.
                # A gap may invalidate a later target before that target closes.
                or (status == "SETTLED" and (type(outcome) is not bool or type(resolved) is not int
                                                  or resolved < target + seconds or resolved > 2**53 - 1))
                or (status == "PENDING" and (outcome is not None or resolved is not None))
                or (status == "VOID_GAP" and (outcome is not None or type(resolved) is not int
                                                   or resolved < row["issuedAt"] or resolved > 2**53 - 1))):
            raise ValueError("Inconsistent forecast resolution")
        grouped[(model, horizon)].append(row)
    if seen != set(forecast_events):
        raise ValueError("Unmatched forecast event")

    groups = []
    for (model, horizon), rows in sorted(grouped.items()):
        counts = {status: sum(row["status"] == status for row in rows) for status in _STATUSES}
        settled = [row for row in rows if row["status"] == "SETTLED"]
        n = len(settled)
        entry = {"modelVersion": model, "horizonCandles": horizon, "issued": len(rows),
                 "settled": n, "pending": counts["PENDING"], "voidGap": counts["VOID_GAP"],
                 "settledFractionOfIssued": n / len(rows), "minimumSettled": min_settled,
                 "sufficientSample": n >= min_settled, "directionAccuracy": None,
                 "wilson95Descriptive": None, "brier": None, "logLoss": None,
                 "expectedCalibrationError": None, "observedUpFraction": None}
        if n >= min_settled:
            correct = sum((row["probability"] > 0.5) == row["outcomeUp"]
                          for row in settled if row["probability"] != 0.5)
            # A p=0.5 forecast abstains; it is NOT a successful directional call.
            directional = sum(row["probability"] != 0.5 for row in settled)
            bins = [[] for _ in range(calibration_bins)]
            for row in settled:
                p = row["probability"]
                bins[min(calibration_bins - 1, int(p * calibration_bins))].append(row)
            ece = sum(len(bucket) / n * abs(sum(r["probability"] for r in bucket) / len(bucket)
                      - sum(r["outcomeUp"] for r in bucket) / len(bucket))
                      for bucket in bins if bucket)
            entry.update(directionAccuracy=(correct / directional if directional else None),
                         wilson95Descriptive=(_wilson(correct, directional) if directional else None),
                         brier=sum((r["probability"] - int(r["outcomeUp"])) ** 2 for r in settled) / n,
                         logLoss=-sum(math.log(r["probability"]) if r["outcomeUp"]
                                      else math.log1p(-r["probability"]) for r in settled) / n,
                         expectedCalibrationError=ece,
                         observedUpFraction=sum(r["outcomeUp"] for r in settled) / n)
            entry["directionalCalls"] = directional
        else:
            entry["directionalCalls"] = None
        groups.append(entry)
    return {"evidence": _EVIDENCE, "sourceAuthenticated": False,
            "liveExecutableQuotes": False, "forwardReturnsVerified": False,
            "profitabilityEstablished": False, "netReturn": None, "maximumDrawdown": None,
            "identity": identity.copy(), "sequence": snapshot["sequence"],
            "issuedTotal": len(forecasts), "groups": groups,
            "limitations": "Unverified journal inputs; conditional settled-only scores, overlapping outcomes, "
                           "selection/missingness and non-independent samples. No executable bid/ask, "
                           "costs, fill reconciliation, forward returns or trading edge."}


def _declared_receipt_delay_percentiles(rows, seconds):
    """Nearest-rank delays after target close, including late declared receipts.

    These are unverified caller-declared timestamps, never provider latency SLAs.
    """
    if not rows:
        return {"receiptDelaySecondsP50": None, "receiptDelaySecondsP95": None}
    delays = sorted(row["resolvedAt"] - row["targetStart"] - seconds for row in rows)
    n = len(delays)
    return {"receiptDelaySecondsP50": delays[math.ceil(n * 0.50) - 1],
            "receiptDelaySecondsP95": delays[math.ceil(n * 0.95) - 1]}


def audit_settled_receipt_lag(snapshot):
    """Opt-in, read-only consistency census of declared settled-candle receipts.

    This does not change historical scorecard/temporal-audit populations:
    those may contain synthetic post-cutoff labels for sensitivity analysis.
    A real ForecastEventStore replay settles only when its target candle
    arrives no later than target close + the declared maximum receipt lag.
    """
    summarize_forecast_snapshot(snapshot)
    seconds = snapshot["identity"]["seconds"]
    lag = snapshot["maxLagSeconds"]
    settled = [row for row in snapshot["forecasts"] if row["status"] == "SETTLED"]
    excess = [row["resolvedAt"] - (row["targetStart"] + seconds + lag)
              for row in settled
              if row["resolvedAt"] > row["targetStart"] + seconds + lag]
    # Group by both frozen model version and horizon: aggregate counts alone can
    # hide a broken receipt path specific to one model or forecast horizon.
    grouped = defaultdict(list)
    for row in settled:
        grouped[(row["modelVersion"], row["horizon"])].append(row)
    by_model_horizon = []
    for (model, horizon), rows in sorted(grouped.items()):
        late = [row["resolvedAt"] - (row["targetStart"] + seconds + lag)
                for row in rows
                if row["resolvedAt"] > row["targetStart"] + seconds + lag]
        by_model_horizon.append({
            "modelVersion": model, "horizonCandles": horizon,
            "settledCount": len(rows), "lateBeyondDeclaredLagCount": len(late),
            "lateFractionOfSettled": len(late) / len(rows),
            "largestExcessSeconds": max(late) if late else None,
            **_declared_receipt_delay_percentiles(rows, seconds),
        })
    return {
        "status": ("DECLARED_SETTLEMENT_LAG_VIOLATIONS" if excess else
                   "NO_SETTLED_OUTCOMES" if not settled else
                   "NO_DECLARED_SETTLEMENT_LAG_VIOLATIONS"),
        "evidence": _EVIDENCE,
        "settledCount": len(settled),
        "lateBeyondDeclaredLagCount": len(excess),
        "largestExcessSeconds": max(excess) if excess else None,
        **_declared_receipt_delay_percentiles(settled, seconds),
        "byModelHorizon": by_model_horizon,
        "sourceAuthenticated": False,
        "prospectiveReceiptVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }


def audit_pending_outcome_deadlines(snapshot, *, as_of):
    """Read-only declared pending-target deadline census at a caller as-of time.

    This is not independent feed or clock evidence. A pending target is overdue
    only *after* target close plus the inclusive declared receipt-lag budget.
    Missing forecast issuances and expected market-session bars are not counted.
    """
    summarize_forecast_snapshot(snapshot)
    if type(as_of) is not int or not 0 <= as_of <= 2**53 - 1:
        raise ValueError("Invalid pending audit as-of time")
    for event in snapshot["events"]:
        received = event.get("receivedAt")
        if type(received) is not int or not 0 <= received <= as_of:
            raise ValueError("Forecast event after pending audit cutoff")
    for row in snapshot["forecasts"]:
        if (row["issuedAt"] > as_of or
                (row["resolvedAt"] is not None and row["resolvedAt"] > as_of)):
            raise ValueError("Forecast resolution after pending audit cutoff")
    seconds = snapshot["identity"]["seconds"]
    lag = snapshot["maxLagSeconds"]
    for row in snapshot["forecasts"]:
        if row["targetStart"] + seconds + lag > 2**53 - 1:
            raise ValueError("Pending audit deadline overflow")

    def summarize(rows):
        pending = [row for row in rows if row["status"] == "PENDING"]
        overdue = sorted(as_of - (row["targetStart"] + seconds + lag)
                         for row in pending if as_of > row["targetStart"] + seconds + lag)
        n_overdue = len(overdue)
        # Stable identities let an operator reconcile each overdue forecast;
        # the list is declared-only, not evidence of a missing market candle.
        overdue_ids = sorted(row["id"] for row in pending
                             if as_of > row["targetStart"] + seconds + lag)
        # Nearest-rank tail ages are descriptive of caller-declared pending
        # receipts, not evidence of provider downtime or market-session bars.
        return {"issuedCount": len(rows),
                "settledCount": sum(row["status"] == "SETTLED" for row in rows),
                "voidGapCount": sum(row["status"] == "VOID_GAP" for row in rows),
                "pendingCount": len(pending),
                "pendingWithinDeclaredWindowCount": len(pending) - len(overdue),
                "overduePendingCount": len(overdue),
                "overdueForecastIds": overdue_ids,
                "overdueFractionOfPending": n_overdue / len(pending) if pending else None,
                "overdueFractionOfIssued": n_overdue / len(rows) if rows else None,
                "longestOverdueSeconds": overdue[-1] if overdue else None,
                "overdueSecondsP50": overdue[math.ceil(n_overdue * 0.50) - 1] if overdue else None,
                "overdueSecondsP95": overdue[math.ceil(n_overdue * 0.95) - 1] if overdue else None}

    grouped = defaultdict(list)
    for row in snapshot["forecasts"]:
        grouped[(row["modelVersion"], row["horizon"])].append(row)
    aggregate = summarize(snapshot["forecasts"])
    return {"status": ("DECLARED_OVERDUE_PENDING" if aggregate["overduePendingCount"]
                       else "NO_DECLARED_OVERDUE_PENDING"),
            "evidence": _EVIDENCE, "asOf": as_of, **aggregate,
            "byModelHorizon": [
                {"modelVersion": model, "horizonCandles": horizon, **summarize(rows)}
                for (model, horizon), rows in sorted(grouped.items())],
            "sourceAuthenticated": False, "prospectiveReceiptVerified": False,
            "sessionCalendarAuthenticated": False, "maySendNotification": False,
            "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False}
