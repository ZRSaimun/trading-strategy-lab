"""Disconnected chronological calibration and drift review of forecast journals.

Consumes only ForecastEventStore.load snapshots. Metrics are descriptive and
cannot authorize alerts, paper fills or real orders. No external I/O.
"""
import math
from collections import defaultdict

from .forecast_prospective_scorecard import summarize_forecast_snapshot


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


def audit_temporal_forecast_calibration(snapshot, *, min_per_window=30,
                                        brier_deterioration=0.05,
                                        max_unresolved_fraction=0.10):
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
    Thresholds are heuristics, not hypothesis tests.
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

    # The scorecard checks the exact evidence marker, identity, sequence,
    # event/forecast correspondence, outcome types and resolution status.
    # It does NOT independently authenticate the journal or its provider.
    summarize_forecast_snapshot(snapshot)
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
        test = [r for r in late_census if r["status"] == "SETTLED"]
        # A SETTLED outcome learned only after the late cohort begins is
        # unavailable to the frozen baseline. Count it as boundary missingness
        # even though the retrospective journal eventually contains a label.
        early_purged = sum(r["status"] == "SETTLED"
                           and (boundary is None or r["resolvedAt"] >= boundary)
                           for r in early)
        early_unavailable = early_unresolved + early_purged
        early_rate = early_unavailable / len(early) if early else 1.0
        late_rate = late_unresolved / len(late) if late else 1.0
        # An issued-stream denominator can hide concentrated missing labels in
        # the fixed nonoverlapping census actually used for scoring. Require
        # BOTH the whole-stream and selected-census fractions to pass. The
        # census is frozen before settlement status is inspected.
        early_census_unavailable = sum(
            r["status"] != "SETTLED" or boundary is None or r["resolvedAt"] >= boundary
            for r in early_census)
        late_census_unresolved = sum(r["status"] != "SETTLED" for r in late_census)
        early_census_rate = (early_census_unavailable / len(early_census)
                             if early_census else 1.0)
        late_census_rate = (late_census_unresolved / len(late_census)
                            if late_census else 1.0)
        sufficient = len(train) >= min_per_window and len(test) >= min_per_window
        complete_enough = (early_rate <= max_unresolved_fraction
                           and late_rate <= max_unresolved_fraction
                           and early_census_rate <= max_unresolved_fraction
                           and late_census_rate <= max_unresolved_fraction)
        entry = {
            "modelVersion": model, "horizonCandles": horizon,
            "issued": len(rows), "earlyIssued": len(early), "lateIssued": len(late),
            "earlyUnresolvedOrVoid": early_unresolved,
            "lateUnresolvedOrVoid": late_unresolved,
            "earlyPurgedForChronology": early_purged,
            "earlyUnavailableAtBoundary": early_unavailable,
            "earlyUnavailableAtBoundaryFraction": early_rate,
            "lateUnresolvedOrVoidFraction": late_rate,
            "earlyNonoverlappingIssued": len(early_census),
            "lateNonoverlappingIssued": len(late_census),
            "earlyCensusUnavailableAtBoundary": early_census_unavailable,
            "lateCensusUnresolvedOrVoid": late_census_unresolved,
            "earlyCensusUnavailableAtBoundaryFraction": early_census_rate,
            "lateCensusUnresolvedOrVoidFraction": late_census_rate,
            "earlyNonoverlappingSettled": len(train),
            "lateNonoverlappingSettled": len(test),
            "earlyBrier": None, "lateBrier": None, "lateBrierDelta": None,
            "lateBrierSkillVsFrozenEarlyClimatology": None,
            "lateMeanProbability": None, "lateObservedUpRate": None,
            "lateAbsoluteCalibrationGap": None, "descriptiveDriftFlag": None,
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
            entry.update(
                earlyBrier=early_brier, lateBrier=late_brier,
                lateBrierDelta=delta,
                lateBrierSkillVsFrozenEarlyClimatology=1 - late_brier / baseline,
                lateMeanProbability=sum(r["probability"] for r in test) / len(test),
                lateObservedUpRate=sum(r["outcomeUp"] for r in test) / len(test),
                lateAbsoluteCalibrationGap=abs(
                    sum(r["probability"] - int(r["outcomeUp"]) for r in test) / len(test)),
                descriptiveDriftFlag=delta >= brier_deterioration,
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
        "identity": snapshot["identity"].copy(),
        "issuedTotal": len(snapshot["forecasts"]), "groups": reports,
        "limitations": "Caller journal unauthenticated; split is retrospective and not an "
                       "untouched holdout; dependent market regimes and sample selection remain; "
                       "missing/void outcomes can bias scores; heuristic drift is not a p-value. "
                       "No executable BID/ASK, transaction costs, fills or trading returns.",
    }
