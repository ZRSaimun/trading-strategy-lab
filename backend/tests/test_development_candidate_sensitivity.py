"""Synthetic sensitivity tests. No market observations or realized P&L."""
import copy

import pytest

from app.development_candidate_census import _hash, candidate_registration_digest
from app.development_candidate_sensitivity import (
    audit_development_candidate_sensitivity as sensitivity,
)
from test_development_candidate_census import DAY, START, fixture


def test_two_folds_withholds_stability_claim_and_execution():
    result = sensitivity(*fixture())
    assert result["status"] == "INSUFFICIENT_FOLDS"
    assert result["evidenceStatus"] == "DECLARED_ONLY"
    assert result["selectedCandidateId"] == "B"
    assert result["declaredMeanMarginToRunnerUp"] == "0.10"
    assert result["declaredWorstSelectedFoldScore"] == "0.20"
    assert result["foldCount"] == 2
    assert result["perFoldWinners"] == {"f1": "B", "f2": "B"}
    assert result["leaveOneFoldOutWinners"] == {"f1": "B", "f2": "B"}
    assert result["winnerChangesOnFoldRemoval"] == 0
    assert result["mayExecuteLiveOrder"] is False
    assert result["mayExecutePaperOrder"] is False
    assert result["validationHoldoutAccess"] is False
    assert result["statisticalSignificanceEstablished"] is False


def test_post_outcome_receipt_is_independent_of_trial_order():
    inputs = fixture()
    original = sensitivity(*inputs)
    inputs[6].reverse()
    assert sensitivity(*inputs) == original


def test_receipt_detects_changed_scores_even_when_winner_unchanged():
    inputs = fixture()
    old = sensitivity(*inputs)
    inputs[6][0]["score"] = "0.11"
    new = sensitivity(*inputs)
    assert new["selectedCandidateId"] == old["selectedCandidateId"]
    assert new["registrationManifestSha256"] == old["registrationManifestSha256"]
    assert new["postOutcomeReceiptSha256"] != old["postOutcomeReceiptSha256"]


def test_receipt_detects_changed_declared_observation_clock():
    inputs = fixture()
    old = sensitivity(*inputs)
    inputs[6][0]["observedAt"] += 1
    new = sensitivity(*inputs)
    assert new["postOutcomeReceiptSha256"] != old["postOutcomeReceiptSha256"]


def test_never_mutates_inputs():
    inputs = fixture()
    before = copy.deepcopy(inputs)
    sensitivity(*inputs)
    assert inputs == before


def add_third_fold(inputs):
    archives, observations, protocol, folds, candidates, registration, trials, selection = inputs
    folds.append({
        "id": "f3", "trainStart": START, "trainEnd": START + 800 * DAY,
        "testStart": START + 802 * DAY, "testEnd": START + 850 * DAY,
    })
    observations.append({
        "id": "t3", "archiveId": "a2",
        "featureStart": START + 810 * DAY,
        "decisionAt": START + 810 * DAY,
        "labelAvailableAt": START + 811 * DAY,
    })
    registration["manifestSha256"] = candidate_registration_digest(
        archives, observations, protocol, folds, candidates
    )
    for candidate in candidates:
        trials.append({
            "candidateId": candidate["id"], "foldId": "f3",
            "configSha256": candidate["configSha256"],
            "sourceSha256": trials[0]["sourceSha256"],
            "testSetSha256": _hash(["t3"]),
            "score": "0.10" if candidate["id"] == "A" else "0.20",
            "observedAt": START + 851 * DAY,
        })
    selection["selectedAt"] = START + 900 * DAY
    selection["trialCount"] = 6
    return inputs


def test_three_folds_winner_persists_but_not_profit_proof():
    inputs = add_third_fold(fixture())
    result = sensitivity(*inputs)
    assert result["status"] == "WINNER_PERSISTS_WITH_FOLD_REMOVAL"
    assert result["leaveOneFoldOutWinners"] == {"f1": "B", "f2": "B", "f3": "B"}
    assert result["winnerChangesOnFoldRemoval"] == 0
    assert result["profitabilityEstablished"] is False
    assert result["trialScoresAuthenticated"] is False


def test_fold_removal_exposes_fragile_winner():
    inputs = add_third_fold(fixture())
    trials = inputs[6]
    for trial in trials:
        cid, fid = trial["candidateId"], trial["foldId"]
        trial["score"] = (
            {"f1": "0.0", "f2": "0.2", "f3": "0.2"}[fid] if cid == "A"
            else {"f1": "0.5", "f2": "0.0", "f3": "0.0"}[fid]
        )
    result = sensitivity(*inputs)
    assert result["selectedCandidateId"] == "B"
    assert result["status"] == "WINNER_CHANGES_WITH_FOLD_REMOVAL"
    assert result["leaveOneFoldOutWinners"] == {"f1": "A", "f2": "B", "f3": "B"}
    assert result["winnerChangesOnFoldRemoval"] == 1
    assert result["declaredMeanMarginToRunnerUp"] == str(
        __import__("decimal").Decimal("0.5") / 3 - __import__("decimal").Decimal("0.4") / 3
    )


def test_tie_break_applies_consistently_to_leave_one_out():
    inputs = add_third_fold(fixture())
    for trial in inputs[6]:
        cid, fid = trial["candidateId"], trial["foldId"]
        trial["score"] = (
            {"f1": "0.2", "f2": "0.2", "f3": "0.1"}[fid] if cid == "A"
            else {"f1": "0.3", "f2": "0.3", "f3": "0.0"}[fid]
        )
    result = sensitivity(*inputs)
    assert result["selectedCandidateId"] == "B"
    assert result["leaveOneFoldOutWinners"] == {"f1": "A", "f2": "A", "f3": "B"}


def test_one_candidate_has_no_mean_margin_or_comparator():
    inputs = fixture()
    inputs[4][:] = [c for c in inputs[4] if c["id"] == "B"]
    inputs[6][:] = [t for t in inputs[6] if t["candidateId"] == "B"]
    inputs[5]["manifestSha256"] = candidate_registration_digest(*inputs[:5])
    inputs[7]["candidateCount"] = 1
    inputs[7]["trialCount"] = 2
    result = sensitivity(*inputs)
    assert result["status"] == "INSUFFICIENT_COMPARATORS"
    assert result["declaredMeanMarginToRunnerUp"] is None
    assert result["winnerChangesOnFoldRemoval"] is None


@pytest.mark.parametrize("mutation", [
    lambda x: x[6].pop(),
    lambda x: x[6][0].__setitem__("score", "NaN"),
    lambda x: x[6][0].__setitem__("sourceSha256", "f" * 64),
    lambda x: x[7].__setitem__("selectedAt", x[3][0]["testStart"]),
    lambda x: x[1][0].__setitem__("realizedReturn", "123"),
    lambda x: x[5].__setitem__("manifestSha256", "0" * 64),
])
def test_revalidates_upstream_fail_closed_census(mutation):
    inputs = fixture()
    mutation(inputs)
    with pytest.raises(ValueError):
        sensitivity(*inputs)


def test_holdout_timing_does_not_affect_sensitivity_receipt():
    inputs = fixture()
    old = sensitivity(*inputs)
    inputs[1][4]["labelAvailableAt"] += 1800
    assert sensitivity(*inputs) == old
