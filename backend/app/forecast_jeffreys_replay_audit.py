"""Disconnected exact causal replay audit for the frozen Jeffreys UTC-phase issuer.

Validates the declared journal by replay, then recomputes each recorded model
probability from the completed-candle prefix. No source authentication, model
approval, alert delivery, paper fill, broker connection, or trading permission.
"""
from collections import defaultdict

from .forecast_causal_issuer import HORIZONS, MODEL_VERSION
from .forecast_event_store import _replay
from .forecast_prospective_scorecard import summarize_forecast_snapshot


def audit_jeffreys_causal_replay(snapshot, *, min_samples=30):
    """Reconcile recorded Jeffreys probabilities against causally available bars.

    This is an *exact implementation* check, not evidence that the model is
    calibrated or that any observations arrived from an entitled live feed.
    Unissued eligible candle slots are descriptive only: an independently
    registered issuance schedule is required to call them missing decisions.
    """
    if type(min_samples) is not int or not 30 <= min_samples <= 1000:
        raise ValueError("Invalid frozen Jeffreys minimum training sample")
    summarize_forecast_snapshot(snapshot)
    events = snapshot["events"]
    replayed = _replay({"version": 1, "identity": snapshot["identity"],
                        "maxLagSeconds": snapshot["maxLagSeconds"],
                        "events": events},
                       events[-1]["receivedAt"] if events else 0)
    if replayed != snapshot["forecasts"]:
        raise ValueError("Declared forecast outcomes do not match causal journal replay")

    seconds = snapshot["identity"]["seconds"]
    model = f"{MODEL_VERSION}-n{min_samples}"
    closes = {}
    wins = {h: 0 for h in HORIZONS}
    trials = {h: 0 for h in HORIZONS}
    eligible = set()
    issued = set()
    matched = 0
    premature = 0
    mismatches = []
    other_models = 0
    by_horizon = defaultdict(lambda: {"issued": 0, "matched": 0,
                                      "probabilityMismatches": 0,
                                      "insufficientTraining": 0})
    for event in events:
        if event["kind"] == "CANDLE":
            start = event["start"]
            closes[start] = event["close"]
            for horizon in HORIZONS:
                base = start - horizon * seconds
                if (base >= 0 and base in closes and
                        (base // seconds) % horizon == 0 and
                        all(base + k * seconds in closes
                            for k in range(1, horizon + 1))):
                    trials[horizon] += 1
                    wins[horizon] += int(event["close"] > closes[base])
                if trials[horizon] >= min_samples:
                    eligible.add((horizon, start))
        else:
            if event["modelVersion"] != model:
                other_models += 1
                continue
            horizon = event["horizon"]
            key = (horizon, event["baseStart"])
            issued.add(key)
            stats = by_horizon[horizon]
            stats["issued"] += 1
            if trials[horizon] < min_samples:
                premature += 1
                stats["insufficientTraining"] += 1
                continue
            expected = (wins[horizon] + 0.5) / (trials[horizon] + 1)
            if event["probability"] == expected:
                matched += 1
                stats["matched"] += 1
            else:
                stats["probabilityMismatches"] += 1
                if len(mismatches) < 50:
                    mismatches.append({"horizonCandles": horizon,
                                       "baseStart": event["baseStart"],
                                       "declaredProbability": event["probability"],
                                       "causalProbability": expected,
                                       "causalTrials": trials[horizon],
                                       "causalUpOutcomes": wins[horizon]})

    total_mismatches = sum(s["probabilityMismatches"] for s in by_horizon.values())
    unissued = eligible - issued
    status = ("OPERATOR_REVIEW_REQUIRED" if total_mismatches or premature else
              "NO_MATCHING_MODEL_ISSUANCES" if not issued else
              "DECLARED_CAUSAL_REPLAY_MATCH_UNVERIFIED")
    return {
        "status": status,
        "evidence": "UNAUTHENTICATED_DISCONNECTED_CAUSAL_REPLAY",
        "modelVersion": model,
        "minimumSamples": min_samples,
        "journalSequence": snapshot["sequence"],
        "recordedModelIssuances": len(issued),
        "exactProbabilityMatches": matched,
        "probabilityMismatchCount": total_mismatches,
        "insufficientTrainingIssuanceCount": premature,
        "first50ProbabilityMismatches": mismatches,
        "eligibleCandleHorizonOpportunitiesDeclared": len(eligible),
        "unissuedEligibleOpportunitiesNotProvenMissing": len(unissued),
        "first50UnissuedEligibleOpportunities": [
            {"horizonCandles": h, "baseStart": b} for h, b in sorted(unissued)[:50]],
        "otherModelIssuancesNotEvaluated": other_models,
        "byHorizon": [
            {"horizonCandles": h, **by_horizon[h],
             "latestCausalTrials": trials[h], "latestCausalUpOutcomes": wins[h]}
            for h in HORIZONS],
        "sourceAuthenticated": False,
        "independentScheduleVerified": False,
        "modelCalibrationVerified": False,
        "forwardReturnsVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
