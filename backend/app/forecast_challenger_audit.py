"""Fail-closed paired challenger audit of disconnected prospective forecast journals.

Research-only: no authenticated provider, notification, paper fill, or order path.
Scores are descriptive, not independent-sample inference or trading returns.
"""
import math

from .forecast_event_store import MAX_EVENTS, _ID, _epoch, _replay

_EVIDENCE = "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"
_KEYS = {"sequence", "identity", "maxLagSeconds", "events", "forecasts", "evidence"}


def compare_prospective_models(snapshot, *, incumbent, challenger, horizon, as_of,
                               min_pairs=30):
    """Compare all same-base forecasts, never a cherry-picked settled subset.

    The caller must first obtain ForecastEventStore.load output. Replaying every
    journal event here independently checks its complete-candle chronology and
    rejects a modified or inconsistent forecast projection. Both models must
    cover exactly the same base candles; ANY unpaired, pending or voided outcome
    withholds all comparative scores. Each horizon is evaluated separately.
    """
    if (type(incumbent) is not str or not _ID.fullmatch(incumbent)
            or type(challenger) is not str or not _ID.fullmatch(challenger)
            or incumbent == challenger or type(horizon) is not int
            or horizon not in (1, 3, 12) or not _epoch(as_of)
            or type(min_pairs) is not int or not 30 <= min_pairs <= 2000):
        raise ValueError("Invalid prospective challenger configuration")
    if (type(snapshot) is not dict or set(snapshot) != _KEYS
            or snapshot["evidence"] != _EVIDENCE
            or type(snapshot["sequence"]) is not int
            or type(snapshot["events"]) is not list
            or len(snapshot["events"]) > MAX_EVENTS
            or snapshot["sequence"] != len(snapshot["events"])
            or type(snapshot["forecasts"]) is not list):
        raise ValueError("Expected validated disconnected forecast snapshot")
    payload = {"version": 1, "identity": snapshot["identity"],
               "maxLagSeconds": snapshot["maxLagSeconds"],
               "events": snapshot["events"]}
    replayed = _replay(payload, as_of)
    if replayed != snapshot["forecasts"]:
        raise ValueError("Forecast projection differs from causal journal replay")

    by_base = {}
    for row in replayed:
        if row["horizon"] != horizon or row["modelVersion"] not in (incumbent, challenger):
            continue
        bucket = by_base.setdefault(row["baseStart"], {})
        if row["modelVersion"] in bucket:
            raise ValueError("Duplicate model/base forecast")
        bucket[row["modelVersion"]] = row

    missing = unresolved = 0
    pairs = []
    for start, bucket in sorted(by_base.items()):
        if set(bucket) != {incumbent, challenger}:
            missing += 1
            continue
        old, new = bucket[incumbent], bucket[challenger]
        if (old["targetStart"] != new["targetStart"]
                or old["baseClose"] != new["baseClose"]
                or (old["status"] == "SETTLED" and new["status"] == "SETTLED"
                    and old["outcomeUp"] != new["outcomeUp"])):
            raise ValueError("Paired outcome or target mismatch")
        if old["status"] != "SETTLED" or new["status"] != "SETTLED":
            unresolved += 1
            continue
        pairs.append((old, new))

    status = "REPORT" if not missing and not unresolved and len(pairs) >= min_pairs else "WITHHELD"
    reason = (None if status == "REPORT" else
              "UNPAIRED_FORECASTS" if missing else
              "PENDING_OR_VOID_OUTCOMES" if unresolved else "INSUFFICIENT_PAIRS")
    result = {"evidence": _EVIDENCE, "sourceAuthenticated": False,
              "liveExecutableQuotes": False, "profitabilityEstablished": False,
              "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False,
              "netReturn": None, "maximumTradingDrawdown": None,
              "status": status, "reason": reason, "incumbent": incumbent,
              "challenger": challenger, "horizonCandles": horizon,
              "identity": snapshot["identity"].copy(), "asOf": as_of,
              "minimumPairs": min_pairs, "baseCandles": len(by_base),
              "unpairedBaseCandles": missing, "unresolvedPairs": unresolved,
              "settledPairs": len(pairs), "incumbentBrier": None,
              "challengerBrier": None, "meanExcessBrier": None,
              "brierSkillVsIncumbent": None, "worstSingleExcessBrier": None,
              "maxCumulativeExcessBrierDrawdown": None,
              "meanAbsoluteProbabilityDifference": None,
              "limitations": "Unverified disconnected inputs, non-independent overlapping "
                             "horizons, self-declared evaluation cutover, no provider "
                             "entitlement, executable quotes, trading costs, fills or returns."}
    if status != "REPORT":
        return result

    old_total = new_total = difference_total = 0.0
    cumulative = minimum_cumulative = maximum_adverse = worst = 0.0
    for old, new in pairs:
        y = int(old["outcomeUp"])
        old_loss = (old["probability"] - y) ** 2
        new_loss = (new["probability"] - y) ** 2
        excess = new_loss - old_loss
        old_total += old_loss
        new_total += new_loss
        difference_total += abs(new["probability"] - old["probability"])
        cumulative += excess
        minimum_cumulative = min(minimum_cumulative, cumulative)
        maximum_adverse = max(maximum_adverse, cumulative - minimum_cumulative)
        worst = max(worst, excess)
    n = len(pairs)
    old_mean, new_mean = old_total / n, new_total / n
    metrics = (old_mean, new_mean, new_mean - old_mean, maximum_adverse, worst)
    if any(not math.isfinite(x) for x in metrics):
        raise ValueError("Nonfinite paired challenger diagnostic")
    result.update(incumbentBrier=old_mean, challengerBrier=new_mean,
                  meanExcessBrier=new_mean - old_mean,
                  brierSkillVsIncumbent=(1 - new_mean / old_mean if old_mean > 0 else None),
                  worstSingleExcessBrier=worst,
                  maxCumulativeExcessBrierDrawdown=maximum_adverse,
                  meanAbsoluteProbabilityDifference=difference_total / n)
    return result
