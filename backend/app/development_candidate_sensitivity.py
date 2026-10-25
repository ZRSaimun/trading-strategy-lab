"""Offline sensitivity audit of a fully declared development candidate census.

No broker calls, holdout outcomes, market data, or execution permissions.
This diagnostic cannot establish statistical significance or trading profit.
"""
from __future__ import annotations

from decimal import Decimal

from app.development_candidate_census import (
    _hash,
    _score,
    audit_development_candidate_census,
)


def audit_development_candidate_sensitivity(
    archives, observations, protocol, folds, candidates,
    registration, trials, selection,
):
    """Revalidate the entire census, then measure fold-removal sensitivity.

    Each score is an unverified, caller-declared dimensionless research metric.
    Leave-one-fold-out selection is descriptive and NOT an unbiased estimate
    of out-of-sample performance or a multiple-testing correction.
    """
    census = audit_development_candidate_census(
        archives, observations, protocol, folds, candidates,
        registration, trials, selection,
    )
    candidate_ids = sorted(c["id"] for c in candidates)
    fold_ids = [f["id"] for f in folds]
    scores = {
        (t["candidateId"], t["foldId"]): _score(t["score"])
        for t in trials
    }
    count = len(fold_ids)
    selected = census["selectedCandidateId"]

    def winner(kept_folds):
        averages = {
            cid: sum((scores[(cid, fid)] for fid in kept_folds), Decimal(0))
            / Decimal(len(kept_folds))
            for cid in candidate_ids
        }
        return sorted(candidate_ids, key=lambda cid: (-averages[cid], cid))[0]

    # An after-the-fact receipt permits exact future reconciliation, but is
    # explicitly NOT a trusted pre-test registration or authenticated score.
    receipt = _hash({
        "engine": "development-candidate-sensitivity-v1",
        "registrationManifestSha256": census["registrationManifestSha256"],
        "trials": sorted(trials, key=lambda t: (t["candidateId"], t["foldId"])),
        "selection": selection,
    })
    per_fold_winners = {
        fid: winner([fid]) for fid in sorted(fold_ids)
    }
    excluded_winners = (
        {fid: winner([other for other in fold_ids if other != fid])
         for fid in sorted(fold_ids)}
        if count >= 2 else {}
    )
    selected_scores = [scores[(selected, fid)] for fid in fold_ids]
    if len(candidate_ids) == 1:
        status = "INSUFFICIENT_COMPARATORS"
        mean_margin = None
    else:
        means = {
            cid: sum((scores[(cid, fid)] for fid in fold_ids), Decimal(0))
            / Decimal(count)
            for cid in candidate_ids
        }
        runner_up = sorted(
            (cid for cid in candidate_ids if cid != selected),
            key=lambda cid: (-means[cid], cid),
        )[0]
        mean_margin = str(means[selected] - means[runner_up])
        if count < 3:
            status = "INSUFFICIENT_FOLDS"
        elif all(cid == selected for cid in excluded_winners.values()):
            status = "WINNER_PERSISTS_WITH_FOLD_REMOVAL"
        else:
            status = "WINNER_CHANGES_WITH_FOLD_REMOVAL"

    return {
        "engine": "development-candidate-sensitivity-v1",
        "status": status,
        "evidenceStatus": "DECLARED_ONLY",
        "registrationManifestSha256": census["registrationManifestSha256"],
        "postOutcomeReceiptSha256": receipt,
        "selectedCandidateId": selected,
        "candidateCount": len(candidate_ids),
        "foldCount": count,
        "trialCount": len(trials),
        "declaredMeanMarginToRunnerUp": mean_margin,
        "declaredWorstSelectedFoldScore": str(min(selected_scores)),
        "perFoldWinners": per_fold_winners,
        "leaveOneFoldOutWinners": excluded_winners,
        "winnerChangesOnFoldRemoval": (
            sum(cid != selected for cid in excluded_winners.values())
            if len(candidate_ids) > 1 else None
        ),
        "sourceAuthenticated": False,
        "externalPreregistrationVerified": False,
        "trialScoresAuthenticated": False,
        "validationHoldoutAccess": False,
        "statisticalSignificanceEstablished": False,
        "profitabilityEstablished": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
        "warning": (
            "All scores and times are declared; the post-outcome receipt is not "
            "a trusted precommitment. Fold-removal sensitivity does not prove "
            "significance, unbiased selection, real net-of-cost returns, "
            "holdout integrity, source authenticity or profitability."
        ),
    }
