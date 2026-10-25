"""Read-only issuance-opportunity census for a disconnected forecast journal.

The declared model population and journal are self-attested. This never
certifies feed completeness, prospective skill, notifications, or orders.
"""
from .forecast_event_store import _epoch, _feed, _ID, _replay

_ALLOWED_HORIZONS = (1, 3, 12)
_EVIDENCE = "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"


def audit_issuance_opportunities(snapshot, *, as_of, model_versions, horizons=(1, 3, 12)):
    """Account for every *observed* candle/model/horizon issuance opportunity.

    No inference is made about candles absent from the journal. A caller must
    preregister the full model population independently of these observations.
    The clock and source metadata are not authenticated by this function.
    """
    if not _epoch(as_of):
        raise ValueError("Invalid census as-of timestamp")
    if (type(model_versions) not in (list, tuple) or not 1 <= len(model_versions) <= 10
            or any(type(m) is not str or not _ID.fullmatch(m) for m in model_versions)
            or len(set(model_versions)) != len(model_versions)):
        raise ValueError("Invalid declared model population")
    if (type(horizons) not in (list, tuple) or not 1 <= len(horizons) <= 3
            or any(type(h) is not int or h not in _ALLOWED_HORIZONS for h in horizons)
            or len(set(horizons)) != len(horizons)):
        raise ValueError("Invalid declared horizon population")
    if (type(snapshot) is not dict or set(snapshot) !=
            {"sequence", "identity", "maxLagSeconds", "events", "forecasts", "evidence"}
            or snapshot["evidence"] != _EVIDENCE or type(snapshot["sequence"]) is not int
            or type(snapshot["events"]) is not list
            or snapshot["sequence"] != len(snapshot["events"])
            or type(snapshot["forecasts"]) is not list):
        raise ValueError("Invalid forecast journal snapshot")
    identity = snapshot["identity"]
    _feed(identity)
    lag = snapshot["maxLagSeconds"]
    if type(lag) is not int or not 0 <= lag <= 3600:
        raise ValueError("Invalid forecast lag")
    # Validate the *entire* event chain and recompute settlements, rather than
    # accepting caller-supplied forecasts, IDs, or reported outcome statuses.
    replayed = _replay({"version": 1, "identity": identity, "maxLagSeconds": lag,
                        "events": snapshot["events"]}, as_of)
    if snapshot["forecasts"] != replayed:
        raise ValueError("Forecast journal outcomes do not match causal replay")
    candles = [e for e in snapshot["events"] if e["kind"] == "CANDLE"]
    issued = {(r["modelVersion"], r["horizon"], r["baseStart"]) for r in replayed}
    undeclared = [r["id"] for r in replayed
                  if r["modelVersion"] not in model_versions or r["horizon"] not in horizons]
    if undeclared:
        raise ValueError("Undeclared model or horizon issued a forecast")
    seconds = identity["seconds"]
    gaps = sum(b["start"] - a["start"] != seconds for a, b in zip(candles, candles[1:]))
    rows = []
    for model in model_versions:
        for horizon in horizons:
            counts = {"issued": 0, "missed": 0, "open": 0, "ineligible": 0}
            missed_starts = []
            for candle in candles:
                base = candle["start"]
                # The event store permits issue times at most lag seconds
                # after base close, but strictly before the next candle close.
                # The integer-second deadline is exclusive.
                deadline = min(base + 2 * seconds, base + seconds + lag + 1)
                if (model, horizon, base) in issued:
                    counts["issued"] += 1
                elif candle["receivedAt"] >= deadline:
                    counts["ineligible"] += 1
                elif as_of < deadline:
                    counts["open"] += 1
                else:
                    counts["missed"] += 1
                    if len(missed_starts) < 20:
                        missed_starts.append(base)
            rows.append({"modelVersion": model, "horizonCandles": horizon,
                         "observedCandleOpportunities": len(candles), **counts,
                         "missedBaseStartsSample": missed_starts,
                         "completeOnObservedCandles": bool(candles) and counts["issued"] == len(candles)})
    return {"mode": "DISCONNECTED_RESEARCH_CENSUS", "sourceAuthenticated": False,
            "declaredPopulationIndependentlyRegistered": False,
            "journalCoversAllMarketCandles": False, "marketSessionVerified": False,
            "liveExecutableQuotes": False, "alertsDelivered": False,
            "paperOrdersPlaced": False, "liveOrdersPermitted": False,
            "netReturn": None, "maximumDrawdown": None,
            "asOf": as_of, "identity": identity.copy(), "journalSequence": snapshot["sequence"],
            "observedCandles": len(candles), "observedInterCandleGaps": gaps,
            "groups": rows,
            "limitations": "Observed journal candles only; absent bars, unregistered models, market sessions, "
                           "source entitlement and caller as-of time cannot be independently verified."}
