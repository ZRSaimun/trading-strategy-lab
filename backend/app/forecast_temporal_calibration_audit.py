"""Disconnected chronological calibration and drift review of forecast journals.

Consumes only ForecastEventStore.load snapshots. Metrics are descriptive and
cannot authorize alerts, paper fills or real orders. No external I/O.
"""
import math
from collections import defaultdict

from .forecast_prospective_scorecard import _wilson, summarize_forecast_snapshot


def _nonoverlapping(rows):
    """Conservatively discard forecasts sharing a base/target close observation."""
    kept = []
    last_target = -1
    for row in rows:
        if row["baseStart"] > last_target:
            kept.append(row)
            last_target = row["targetStart"]
    return kept


def _brier(rows):
    return sum((r["probability"] - int(r["outcomeUp"])) ** 2 for r in rows) / len(rows)


def _log_loss(rows):
    """Bernoulli log score in natural-log units; descriptive, not trading P&L.

    The journal validator requires strictly interior finite probabilities.
    log1p(-p) preserves precision for negative outcomes with p near zero.
    """
    return sum(-math.log(r["probability"]) if r["outcomeUp"]
               else -math.log1p(-r["probability"]) for r in rows) / len(rows)


def _calibration_ece10(rows):
    """Descriptive 10-bin ECE; do not interpret as statistical significance.

    Sum absolute within-bin probability/outcome differences before weighting.
    Unlike the global mean calibration gap, opposite errors cannot cancel
    across bins. Sparse bins and dependent outcomes still limit reliability.
    """
    totals = [[0.0, 0] for _ in range(10)]
    for row in rows:
        bucket = totals[min(9, int(row["probability"] * 10))]
        bucket[0] += row["probability"]
        bucket[1] += int(row["outcomeUp"])
    return sum(abs(predicted - observed) for predicted, observed in totals) / len(rows)



def _calibration_bin_diagnostics10(rows):
    """Fixed ten-bin audit trail for ECE, on the same settled scoring census.

    Empty bins have null rates; no missing observations are synthesized.
    Bin 9 includes the upper endpoint probability 1.0.
    """
    bins = [[0.0, 0, 0] for _ in range(10)]
    for row in rows:
        bucket = bins[min(9, int(row["probability"] * 10))]
        bucket[0] += row["probability"]
        bucket[1] += int(row["outcomeUp"])
        bucket[2] += 1
    return [
        {"bin": index, "count": count,
         "meanProbability": predicted / count if count else None,
         "observedUpRate": observed / count if count else None,
         "observedUpWilson95Descriptive": _wilson(observed, count) if count else None,
         "lowSupportUnder30": count < 30 if count else None}
        for index, (predicted, observed, count) in enumerate(bins)
    ]


def _confidence_tail_diagnostics(rows):
    """Descriptive realized error in the fixed >=90% binary-confidence tail.

    Includes p<=0.10 for DOWN and p>=0.90 for UP; neither side is an
    executable trading signal. A zero-count tail has no observed error rate.
    """
    tail = [r for r in rows if r["probability"] <= 0.10
            or r["probability"] >= 0.90]
    count = len(tail)
    wrong = sum(
        (r["probability"] >= 0.90 and not r["outcomeUp"])
        or (r["probability"] <= 0.10 and r["outcomeUp"])
        for r in tail
    )
    return {
        "lateHighConfidenceCount": count,
        "lateHighConfidenceFractionOfSettled": count / len(rows),
        "lateHighConfidenceWrong": wrong,
        "lateHighConfidenceWrongFraction": wrong / count if count else None,
        "lateHighConfidenceWrongWilson95Descriptive":
            _wilson(wrong, count) if count else None,
        "lateHighConfidenceLowSupportUnder30": count < 30 if count else None,
    }


def audit_temporal_forecast_calibration(snapshot, *, min_per_window=30,
                                        brier_deterioration=0.05,
                                        max_unresolved_fraction=0.10,
                                        evaluation_as_of=None):
    """Review pre/post issuance cohorts without future-informed baseline fitting.

    Split ALL issued records chronologically, before looking at outcomes. The
    early climatology uses only resolved outcomes available BEFORE the first
    late issuance; the late cohort is never used to fit that baseline. Adjacent
    and overlapping forecast outcomes are conservatively thinned. Incomplete
    cohorts withhold scores. Early settled labels unavailable at the split
    boundary count toward the early selection-risk fraction, not just pending
    or void labels. Apply missingness limits to BOTH all issued forecasts and
    the fixed nonoverlapping census used for scores, so overlapping issued
    records cannot dilute missingness concentrated in the evaluated sample.
    An optional caller-declared evaluation_as_of prevents using late labels
    resolved after that cutoff. The cutoff and journal are NOT authenticated
    and do not establish a prospective holdout. Thresholds are heuristics,
    not hypothesis tests.
    """
    if type(min_per_window) is not int or not 30 <= min_per_window <= 1000:
        raise ValueError("Invalid independent sample minimum")
    if (type(brier_deterioration) not in (float, int)
            or not math.isfinite(brier_deterioration)
            or not 0 < brier_deterioration <= 1):
        raise ValueError("Invalid Brier deterioration threshold")
    if (type(max_unresolved_fraction) not in (float, int)
            or not math.isfinite(max_unresolved_fraction)
            or not 0 <= max_unresolved_fraction < 1):
        raise ValueError("Invalid unresolved fraction threshold")

    if (evaluation_as_of is not None and
            (type(evaluation_as_of) is not int or
             not 0 <= evaluation_as_of <= 2**53 - 1)):
        raise ValueError("Invalid declared evaluation cutoff")

    # The scorecard checks the exact evidence marker, identity, sequence,
    # event/forecast correspondence, outcome types and resolution status.
    # It does NOT independently authenticate the journal or its provider.
    summarize_forecast_snapshot(snapshot)
    if (evaluation_as_of is not None and
            any(r["issuedAt"] > evaluation_as_of for r in snapshot["forecasts"])):
        raise ValueError("Declared evaluation cutoff predates issued forecasts")
    seconds = snapshot["identity"]["seconds"]
    groups = defaultdict(list)
    for row in snapshot["forecasts"]:
        if (row["baseStart"] < 0 or row["baseStart"] % seconds
                or not row["baseStart"] + seconds <= row["issuedAt"] < row["baseStart"] + 2 * seconds
                or (row["status"] == "SETTLED"
                    and row["resolvedAt"] < row["targetStart"] + seconds)):
            raise ValueError("Invalid causal forecast or outcome chronology")
        groups[(row["modelVersion"], row["horizon"])].append(row)

    reports = []
    for (model, horizon), unsorted in sorted(groups.items()):
        rows = sorted(unsorted, key=lambda r: (r["baseStart"], r["issuedAt"]))
        if any(a["baseStart"] >= b["baseStart"] or a["issuedAt"] > b["issuedAt"]
               for a, b in zip(rows, rows[1:])):
            raise ValueError("Duplicate or retrograde model/horizon issuance")
        split = len(rows) // 2
        early, late = rows[:split], rows[split:]
        early_unresolved = sum(r["status"] != "SETTLED" for r in early)
        late_unresolved = sum(r["status"] != "SETTLED" for r in late)
        boundary = late[0]["issuedAt"] if late else None
        # The early baseline cannot learn from an outcome resolved after the
        # late evaluation period began. This is a strict chronological purge.
        # Select the independent-ish sampling census from ALL issued forecasts
        # before inspecting settlement status. Selecting settled rows first can
        # shift the sample to later, conveniently observed outcomes when an
        # earlier forecast is pending/void (outcome-dependent selection).
        early_census = _nonoverlapping(early)
        late_census = _nonoverlapping(late)
        train = [r for r in early_census if r["status"] == "SETTLED"
                 and boundary is not None and r["resolvedAt"] < boundary]
        test = [r for r in late_census if r["status"] == "SETTLED"
                and (evaluation_as_of is None or r["resolvedAt"] <= evaluation_as_of)]
        # A SETTLED outcome learned only after the late cohort begins is
        # unavailable to the frozen baseline. Count it as boundary missingness
        # even though the retrospective journal eventually contains a label.
        early_purged = sum(r["status"] == "SETTLED"
                           and (boundary is None or r["resolvedAt"] >= boundary)
                           for r in early)
        early_unavailable = early_unresolved + early_purged
        early_rate = early_unavailable / len(early) if early else 1.0
        late_settled_after_cutoff = sum(
            r["status"] == "SETTLED" and evaluation_as_of is not None
            and r["resolvedAt"] > evaluation_as_of for r in late)
        late_unavailable = late_unresolved + late_settled_after_cutoff
        late_rate = late_unresolved / len(late) if late else 1.0
        late_as_of_rate = late_unavailable / len(late) if late else 1.0
        # An issued-stream denominator can hide concentrated missing labels in
        # the fixed nonoverlapping census actually used for scoring. Require
        # BOTH the whole-stream and selected-census fractions to pass. The
        # census is frozen before settlement status is inspected.
        early_census_unavailable = sum(
            r["status"] != "SETTLED" or boundary is None or r["resolvedAt"] >= boundary
            for r in early_census)
        late_census_unresolved = sum(r["status"] != "SETTLED" for r in late_census)
        late_census_after_cutoff = sum(
            r["status"] == "SETTLED" and evaluation_as_of is not None
            and r["resolvedAt"] > evaluation_as_of for r in late_census)
        early_census_rate = (early_census_unavailable / len(early_census)
                             if early_census else 1.0)
        late_census_rate = (late_census_unresolved / len(late_census)
                            if late_census else 1.0)
        late_census_as_of_rate = (
            (late_census_unresolved + late_census_after_cutoff) / len(late_census)
            if late_census else 1.0)
        sufficient = len(train) >= min_per_window and len(test) >= min_per_window
        complete_enough = (early_rate <= max_unresolved_fraction
                           and late_as_of_rate <= max_unresolved_fraction
                           and early_census_rate <= max_unresolved_fraction
                           and late_census_as_of_rate <= max_unresolved_fraction)
        entry = {
            "modelVersion": model, "horizonCandles": horizon,
            "issued": len(rows), "earlyIssued": len(early), "lateIssued": len(late),
            "earlyUnresolvedOrVoid": early_unresolved,
            "lateUnresolvedOrVoid": late_unresolved,
            "earlyPurgedForChronology": early_purged,
            "earlyUnavailableAtBoundary": early_unavailable,
            "earlyUnavailableAtBoundaryFraction": early_rate,
            "lateUnresolvedOrVoidFraction": late_rate,
            "lateSettledAfterDeclaredAsOf": late_settled_after_cutoff,
            "lateUnavailableAtDeclaredAsOfFraction": late_as_of_rate,
            "earlyNonoverlappingIssued": len(early_census),
            "lateNonoverlappingIssued": len(late_census),
            "earlyCensusUnavailableAtBoundary": early_census_unavailable,
            "lateCensusUnresolvedOrVoid": late_census_unresolved,
            "lateCensusSettledAfterDeclaredAsOf": late_census_after_cutoff,
            "earlyCensusUnavailableAtBoundaryFraction": early_census_rate,
            "lateCensusUnresolvedOrVoidFraction": late_census_rate,
            "lateCensusUnavailableAtDeclaredAsOfFraction": late_census_as_of_rate,
            "earlyNonoverlappingSettled": len(train),
            "lateNonoverlappingSettled": len(test),
            "earlyBrier": None, "lateBrier": None, "lateBrierDelta": None,
            "earlyLogLoss": None, "lateLogLoss": None, "lateLogLossDelta": None,
            "lateLogLossSkillVsFrozenEarlyClimatology": None,
            "lateBrierSkillVsFrozenEarlyClimatology": None,
            "lateMeanProbability": None, "lateObservedUpRate": None,
            "lateAbsoluteCalibrationGap": None,
            "lateExpectedCalibrationError10": None, "lateEceBins10": None,
            "lateEceOccupiedBinsUnder30": None,
            "lateEceMinOccupiedBinCount": None,
            "lateHighConfidenceCount": None,
            "lateHighConfidenceFractionOfSettled": None,
            "lateHighConfidenceWrong": None,
            "lateHighConfidenceWrongFraction": None,
            "lateHighConfidenceWrongWilson95Descriptive": None,
            "lateHighConfidenceLowSupportUnder30": None,
            "descriptiveDriftFlag": None,
            "status": "INSUFFICIENT_NONOVERLAPPING_OUTCOMES" if not sufficient
                      else "UNRESOLVED_SELECTION_RISK" if not complete_enough
                      else "DESCRIPTIVE_ONLY",
        }
        if sufficient and complete_enough:
            early_brier, late_brier = _brier(train), _brier(test)
            # Jeffreys-smoothed historical climatology, fitted ONLY on
            # pre-boundary resolved outcomes. This is not a market benchmark.
            prior_up = (sum(r["outcomeUp"] for r in train) + 0.5) / (len(train) + 1)
            baseline = sum((prior_up - int(r["outcomeUp"])) ** 2 for r in test) / len(test)
            delta = late_brier - early_brier
            early_log, late_log = _log_loss(train), _log_loss(test)
            frozen_log = sum(-math.log(prior_up) if r["outcomeUp"]
                             else -math.log1p(-prior_up) for r in test) / len(test)
            late_bins = _calibration_bin_diagnostics10(test)
            occupied = [b["count"] for b in late_bins if b["count"]]
            entry.update(
                earlyBrier=early_brier, lateBrier=late_brier,
                lateBrierDelta=delta,
                earlyLogLoss=early_log, lateLogLoss=late_log,
                lateLogLossDelta=late_log - early_log,
                lateLogLossSkillVsFrozenEarlyClimatology=1 - late_log / frozen_log,
                lateBrierSkillVsFrozenEarlyClimatology=1 - late_brier / baseline,
                lateMeanProbability=sum(r["probability"] for r in test) / len(test),
                lateObservedUpRate=sum(r["outcomeUp"] for r in test) / len(test),
                lateAbsoluteCalibrationGap=abs(
                    sum(r["probability"] - int(r["outcomeUp"]) for r in test) / len(test)),
                lateExpectedCalibrationError10=_calibration_ece10(test),
                lateEceBins10=late_bins,
                lateEceOccupiedBinsUnder30=sum(n < 30 for n in occupied),
                lateEceMinOccupiedBinCount=min(occupied),
                descriptiveDriftFlag=delta >= brier_deterioration,
                **_confidence_tail_diagnostics(test),
            )
            if entry["descriptiveDriftFlag"]:
                entry["status"] = "DESCRIPTIVE_BRIER_DETERIORATION_REVIEW"
        reports.append(entry)
    return {
        "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL",
        "sourceAuthenticated": False, "independentHoldoutVerified": False,
        "statisticalSignificanceEstablished": False, "profitabilityEstablished": False,
        "forwardNetReturn": None, "maximumDrawdown": None,
        "maySendNotification": False, "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
        "evaluationAsOfDeclared": evaluation_as_of,
        "evaluationCutoffAuthenticated": False,
        "identity": snapshot["identity"].copy(),
        "issuedTotal": len(snapshot["forecasts"]), "groups": reports,
        "limitations": "Caller journal unauthenticated; split is retrospective and not an "
                       "untouched holdout; dependent market regimes and sample selection remain; "
                       "declared as-of cutoff and settlement times are not independently verified; "
                       "missing/void outcomes can bias scores; log loss heavily penalizes "
                       "confident wrong probabilities and is not financial loss; "
                       "high-confidence tail errors are descriptive and depend on "
                       "the fixed 90% threshold; empty tails have no error estimate; "
                       "10-bin ECE is bin-dependent "
                       "and noisy with sparse bins; binomial Wilson ranges assume "
                       "independence that is not established; heuristic drift is not a p-value. "
                       "No executable BID/ASK, transaction costs, fills or trading returns.",
    }
