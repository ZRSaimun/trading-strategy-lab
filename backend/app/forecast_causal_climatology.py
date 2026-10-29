"""Offline prequential comparator for validated, unverified forecast journals.

No market ingestion, notification, order, broker adapter, or persistent write.
"""
from collections import defaultdict
import math

from .forecast_prospective_scorecard import summarize_forecast_snapshot


def audit_causal_climatology(snapshot, *, evaluation_as_of, min_training=30,
                             min_scored=30, max_unavailable_fraction=0.10):
    """Compare issued probabilities to a horizon/model-isolated causal baseline.

    Training receipts must precede issuance strictly. Fix nonoverlapping
    training membership before reading status; never synthesize gap labels.
    Caller-declared clocks are NOT independently authenticated.
    """
    if type(evaluation_as_of) is not int or not 0 <= evaluation_as_of <= 2**53 - 1:
        raise ValueError("Invalid declared evaluation cutoff")
    if (type(min_training) is not int or not 30 <= min_training <= 5000 or
            type(min_scored) is not int or not 30 <= min_scored <= 5000 or
            type(max_unavailable_fraction) not in (int, float) or
            not math.isfinite(max_unavailable_fraction) or
            not 0 <= max_unavailable_fraction <= 0.25):
        raise ValueError("Invalid causal baseline review settings")
    validated = summarize_forecast_snapshot(snapshot)
    forecasts = snapshot["forecasts"]
    if any(row["issuedAt"] > evaluation_as_of for row in forecasts):
        raise ValueError("Evaluation cutoff predates an issued forecast")
    seconds = snapshot["identity"]["seconds"]
    groups = defaultdict(list)
    for row in forecasts:
        groups[(row["modelVersion"], row["horizon"])].append(row)
    results = []
    for (model, horizon), rows in sorted(groups.items()):
        rows = sorted(rows, key=lambda r: (r["issuedAt"], r["baseStart"], r["id"]))
        if any(b["baseStart"] <= a["baseStart"] for a, b in zip(rows, rows[1:])):
            raise ValueError("Repeated or retroactive model/horizon base candle")
        matured = eligible = unavailable = training_rejected = scored = 0
        baseline_brier = issued_brier = baseline_log = issued_log = 0.0
        regret_brier_low = regret_brier_high = 0.0
        regret_log_low = regret_log_high = 0.0
        first_baseline = min_history = max_history = None
        last_evaluation_target = -1
        overlapping_matured_excluded = 0
        for i, current in enumerate(rows):
            if current["targetStart"] + seconds > evaluation_as_of:
                continue
            matured += 1
            # Fix the evaluation census BEFORE looking at training support or
            # outcomes. Shared base/target closes are not independent trials.
            if current["baseStart"] <= last_evaluation_target:
                overlapping_matured_excluded += 1
                continue
            last_evaluation_target = current["targetStart"]
            last_target = -1
            census = []
            for previous in rows[:i]:
                if previous["targetStart"] + seconds >= current["issuedAt"]:
                    continue
                if previous["baseStart"] > last_target:
                    census.append(previous)
                    last_target = previous["targetStart"]
            observed = [r for r in census if r["status"] == "SETTLED"
                        and r["resolvedAt"] < current["issuedAt"]]
            if (len(observed) < min_training or not census or
                    (len(census) - len(observed)) / len(census) > max_unavailable_fraction):
                training_rejected += 1
                continue
            eligible += 1
            prior_up = sum(r["outcomeUp"] for r in observed)
            p = (prior_up + 0.5) / (len(observed) + 1)
            q = current["probability"]
            # Counterfactual binary labels on the FIXED eligible census.
            # These are selection-risk bounds, never invented settlements.
            brier_down = q * q - p * p
            brier_up = (1 - q) ** 2 - (1 - p) ** 2
            log_down = math.log1p(-p) - math.log1p(-q)
            log_up = math.log(p) - math.log(q)
            if current["status"] != "SETTLED" or current["resolvedAt"] > evaluation_as_of:
                unavailable += 1
                regret_brier_low += min(brier_down, brier_up)
                regret_brier_high += max(brier_down, brier_up)
                regret_log_low += min(log_down, log_up)
                regret_log_high += max(log_down, log_up)
                continue
            regret_brier = brier_up if current["outcomeUp"] else brier_down
            regret_log = log_up if current["outcomeUp"] else log_down
            regret_brier_low += regret_brier
            regret_brier_high += regret_brier
            regret_log_low += regret_log
            regret_log_high += regret_log
            if first_baseline is None:
                first_baseline = p
            min_history = len(observed) if min_history is None else min(min_history, len(observed))
            max_history = len(observed) if max_history is None else max(max_history, len(observed))
            y = int(current["outcomeUp"])
            baseline_brier += (p - y) ** 2
            issued_brier += (q - y) ** 2
            baseline_log += -math.log(p) if y else -math.log1p(-p)
            issued_log += -math.log(q) if y else -math.log1p(-q)
            scored += 1
        missing_fraction = unavailable / eligible if eligible else None
        sufficient = (scored >= min_scored and eligible > 0 and
                      missing_fraction <= max_unavailable_fraction)
        results.append({
            "modelVersion": model, "horizonCandles": horizon,
            "issued": len(rows), "maturedAtDeclaredCutoff": matured,
            "nonoverlappingMaturedCensus": matured - overlapping_matured_excluded,
            "overlappingMaturedExcluded": overlapping_matured_excluded,
            "trainingRejected": training_rejected, "baselineEligible": eligible,
            "scored": scored, "unavailable": unavailable,
            "unavailableFraction": missing_fraction,
            "status": ("INSUFFICIENT_CAUSAL_SAMPLE" if scored < min_scored else
                       "UNAVAILABLE_OUTCOME_SELECTION_RISK" if not sufficient else
                       "DESCRIPTIVE_ONLY"),
            "firstScoredBaselineProbability": first_baseline if sufficient else None,
            "minCausalTrainingOutcomes": min_history if sufficient else None,
            "maxCausalTrainingOutcomes": max_history if sufficient else None,
            "issuedBrier": issued_brier / scored if sufficient else None,
            "causalBaselineBrier": baseline_brier / scored if sufficient else None,
            "pairedBrierRegretIssuedMinusBaseline":
                (issued_brier - baseline_brier) / scored if sufficient else None,
            "pairedBrierRegretBestCaseEligibleCensus":
                regret_brier_low / eligible if sufficient else None,
            "pairedBrierRegretWorstCaseEligibleCensus":
                regret_brier_high / eligible if sufficient else None,
            "issuedLogLoss": issued_log / scored if sufficient else None,
            "causalBaselineLogLoss": baseline_log / scored if sufficient else None,
            "pairedLogLossRegretIssuedMinusBaseline":
                (issued_log - baseline_log) / scored if sufficient else None,
            "pairedLogLossRegretBestCaseEligibleCensus":
                regret_log_low / eligible if sufficient else None,
            "pairedLogLossRegretWorstCaseEligibleCensus":
                regret_log_high / eligible if sufficient else None,
        })
    return {
        "evidence": validated["evidence"], "evaluationAsOfDeclared": evaluation_as_of,
        "evaluationCutoffAuthenticated": False, "sourceAuthenticated": False,
        "independentHoldoutVerified": False, "liveExecutableQuotes": False,
        "profitabilityEstablished": False, "netPaperReturn": None,
        "maximumDrawdown": None, "maySendNotification": False,
        "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False,
        "identity": validated["identity"], "issuedTotal": len(forecasts),
        "groups": results,
        "limitations": "Unverified journal and cutoff, dependent observations, selection, "
                       "missing labels and regimes. No authenticated feed, independent "
                       "holdout, executable quotes, fills, costs or trading returns.",
    }
