"""Invented, offline cross-fold holdout membership regressions."""
import copy
from datetime import datetime, timezone

import pytest

from app.declared_holdout_release_gate import prepare_declared_holdout_census_sha256
from app.declared_holdout_fold_isolation import audit_declared_holdout_fold_isolation


def _utc(year):
    return int(datetime(year, 1, 1, tzinfo=timezone.utc).timestamp())


def _fold(index):
    start, end = _utc(2020 + 2 * index), _utc(2022 + 2 * index) - 10 * 86400
    source_sha = f"{index + 1:064x}"
    census = [dict(observation_id=f"obs-{i:03d}",
                   row_sha256=f"{index * 1000 + i + 100:064x}",
                   source_sha256=source_sha,
                   decision_at_utc=start + (i + 1) * 86400,
                   label_available_at_utc=start + (i + 2) * 86400)
              for i in range(40)]
    manifest = dict(
        study_id="fixed-study", candidate_id="fixed-candidate",
        candidate_config_sha256="b" * 64,
        selection_evidence_sha256=f"{index + 300:064x}",
        validation_end_at_utc=start - 5 * 86400,
        selected_at_utc=start - 3 * 86400,
        registered_at_utc=start - 2 * 86400,
        holdout_start_at_utc=start, holdout_end_at_utc=end,
        embargo_seconds=86400, expected_holdout_count=len(census),
        holdout_census_sha256=prepare_declared_holdout_census_sha256(census),
        source=dict(provider="Synthetic", venue="Offline", instrument="XAUUSD-CFD",
                    quote_side="BID", account_alias="paper-only",
                    settlement_currency="GBP", utc_convention="UTC",
                    archive_sha256=source_sha),
    )
    return dict(manifest=manifest, census=census)


def _valid():
    return [_fold(i) for i in range(3)]


def test_three_two_year_windows_are_membership_only():
    result = audit_declared_holdout_fold_isolation(_valid())
    assert result["status"] == "DECLARED_MEMBERSHIP_ONLY"
    assert result["fold_count"] == 3
    assert result["observation_count"] == 120
    assert len({x["archive_sha256"] for x in result["folds"]}) == 3
    for name in ("source_bytes_independently_authenticated",
                 "holdout_untouched_independently_verified", "broker_costs_verified",
                 "profitable_edge_verified", "may_execute_demo_order", "may_execute_real_order"):
        assert result[name] is False
    assert "net_cash" not in result
    assert result["min_declared_label_embargo_slack_seconds"] > 0


@pytest.mark.parametrize("mutate", [
    lambda f: f.reverse(),
    lambda f: f[1]["manifest"].update(holdout_start_at_utc=f[0]["manifest"]["holdout_end_at_utc"] - 1),
    lambda f: f[1]["manifest"].update(selected_at_utc=f[0]["manifest"]["holdout_end_at_utc"] - 1),
    lambda f: f[1]["manifest"]["source"].update(archive_sha256=f[0]["manifest"]["source"]["archive_sha256"]),
    lambda f: f[1]["manifest"].update(candidate_config_sha256="f" * 64),
    lambda f: f[1]["manifest"].update(candidate_id="another-candidate"),
    lambda f: f[1]["manifest"]["source"].update(quote_side="ASK"),
    lambda f: f[1]["census"][0].update(row_sha256=f[0]["census"][0]["row_sha256"]),
    lambda f: f[1].update(outcomes=[]),
])
def test_cross_fold_leakage_and_identity_changes_fail_closed(mutate):
    folds = _valid()
    mutate(folds)
    # Recommit local declarations so cross-fold checks cannot be bypassed
    # simply by supplying fresh caller-controlled manifest digests.
    for fold in folds:
        for row in fold["census"]:
            if fold["manifest"]["source"]["archive_sha256"] != row["source_sha256"]:
                row["source_sha256"] = fold["manifest"]["source"]["archive_sha256"]
        fold["manifest"]["holdout_census_sha256"] = prepare_declared_holdout_census_sha256(fold["census"])
    with pytest.raises(ValueError):
        audit_declared_holdout_fold_isolation(folds)


def test_previous_labels_must_mature_before_next_selection():
    folds = _valid()
    folds[0]["census"][-1]["label_available_at_utc"] = folds[1]["manifest"]["selected_at_utc"]
    folds[0]["manifest"]["holdout_census_sha256"] = prepare_declared_holdout_census_sha256(folds[0]["census"])
    with pytest.raises(ValueError, match="labels not mature"):
        audit_declared_holdout_fold_isolation(folds)


def test_outcome_mutation_cannot_enter_membership_only_audit():
    folds = copy.deepcopy(_valid())
    folds[2]["census"][0]["gross_cash"] = "999.0000"
    with pytest.raises(ValueError, match="census"):
        audit_declared_holdout_fold_isolation(folds)


@pytest.mark.parametrize("folds", [[], [_fold(0)], [_fold(0)] * 25, "not-a-list"])
def test_population_bounds_fail_closed(folds):
    with pytest.raises(ValueError):
        audit_declared_holdout_fold_isolation(folds)


def test_maximum_24_distinct_declared_folds_remain_membership_only():
    # 24 synthetic, two-year, source-disjoint windows: upper protocol bound.
    folds = [_fold(i) for i in range(24)]
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["fold_count"] == 24
    assert result["observation_count"] == 24 * 40
    assert len({item["archive_sha256"] for item in result["folds"]}) == 24
    assert result["source_bytes_independently_authenticated"] is False
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_previous_label_embargo_equality_is_allowed_but_one_second_late_fails():
    folds = _valid()
    selected = folds[1]["manifest"]["selected_at_utc"]
    embargo = folds[1]["manifest"]["embargo_seconds"]
    # Equality is the permitted boundary: label_available + embargo <= selected.
    folds[0]["census"][-1]["label_available_at_utc"] = selected - embargo
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    assert audit_declared_holdout_fold_isolation(folds)["fold_count"] == 3

    folds[0]["census"][-1]["label_available_at_utc"] += 1
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    with pytest.raises(ValueError, match="labels not mature"):
        audit_declared_holdout_fold_isolation(folds)


@pytest.mark.parametrize("field,replacement", [
    ("provider", "AnotherProvider"),
    ("venue", "AnotherVenue"),
    ("instrument", "XAGUSD-CFD"),
    ("account_alias", "different-paper-account"),
    ("settlement_currency", "USD"),
])
def test_cross_fold_source_identity_changes_fail_with_recommitted_manifest(
    field, replacement
):
    folds = _valid()
    folds[1]["manifest"]["source"][field] = replacement
    # The census commitment remains valid, so rejection must come from
    # cross-fold source identity rather than an unrelated census mismatch.
    with pytest.raises(ValueError, match="source convention changed"):
        audit_declared_holdout_fold_isolation(folds)


def test_declared_label_embargo_slack_reports_exact_boundary_without_outcomes():
    folds = _valid()
    selected = folds[1]["manifest"]["selected_at_utc"]
    embargo = folds[1]["manifest"]["embargo_seconds"]
    folds[0]["census"][-1]["label_available_at_utc"] = selected - embargo
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    original = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_label_embargo_slack_seconds"] == 0
    assert result["status"] == "DECLARED_MEMBERSHIP_ONLY"
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert result["profitable_edge_verified"] is False
    assert "net_cash" not in result
    assert folds == original  # Audit must never rewrite caller declarations.

    # Moving the previous label one second earlier yields one second of slack.
    folds[0]["census"][-1]["label_available_at_utc"] -= 1
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    assert audit_declared_holdout_fold_isolation(folds)[
        "min_declared_label_embargo_slack_seconds"
    ] == 1


def test_declared_slack_is_minimum_over_all_fold_transitions():
    folds = _valid()
    # Make only the second transition tight, leaving the first unchanged.
    selected = folds[2]["manifest"]["selected_at_utc"]
    embargo = folds[2]["manifest"]["embargo_seconds"]
    folds[1]["census"][-1]["label_available_at_utc"] = selected - embargo - 2
    folds[1]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[1]["census"])
    )
    assert audit_declared_holdout_fold_isolation(folds)[
        "min_declared_label_embargo_slack_seconds"
    ] == 2


def test_earliest_decision_late_label_blocks_later_fold():
    # Label availability need not follow decision order. A naive check of the
    # final census row would miss the longest-maturing earlier observation.
    folds = _valid()
    later = folds[1]["manifest"]
    earliest = folds[0]["census"][0]
    earliest["label_available_at_utc"] = (
        later["selected_at_utc"] - later["embargo_seconds"] + 1
    )
    assert (earliest["label_available_at_utc"] >
            folds[0]["census"][-1]["label_available_at_utc"])
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    with pytest.raises(ValueError, match="labels not mature"):
        audit_declared_holdout_fold_isolation(folds)

    # The exact boundary is permitted, but remains only a declared clock.
    earliest["label_available_at_utc"] -= 1
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_label_embargo_slack_seconds"] == 0
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False


def test_later_folds_embargo_not_earlier_folds_controls_slack():
    folds = _valid()
    later = folds[1]["manifest"]
    later["embargo_seconds"] = 2 * 86400
    # The later selection is exactly two days after its validation end,
    # so both the one- and two-day later-fold embargo are valid.
    earliest = folds[0]["census"][0]
    earliest["label_available_at_utc"] = (
        later["selected_at_utc"] - later["embargo_seconds"] - 3
    )
    folds[0]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[0]["census"])
    )
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_label_embargo_slack_seconds"] == 3
    assert "net_cash" not in result

    # Reducing only the *later* embargo adds exactly one day of slack.
    later["embargo_seconds"] = 86400
    assert audit_declared_holdout_fold_isolation(folds)[
        "min_declared_label_embargo_slack_seconds"
    ] == 86403


@pytest.mark.parametrize("seed", range(48))
def test_randomized_nonmonotonic_label_maturity_matches_independent_embargo_oracle(seed):
    """A label can mature long after its decision/window, without order assumptions.

    This compares the audit against a separate per-transition maximum-label
    oracle; all dates and digests are synthetic, caller-controlled fixtures.
    """
    import random

    rng = random.Random(20261028 + seed)
    folds = _valid()
    expected_slacks = []
    for previous, later in zip(folds, folds[1:]):
        manifest = later["manifest"]
        chosen = previous["census"][rng.randrange(len(previous["census"]))]
        slack = rng.randrange(0, 1001)
        chosen["label_available_at_utc"] = (
            manifest["selected_at_utc"] - manifest["embargo_seconds"] - slack
        )
        previous["manifest"]["holdout_census_sha256"] = (
            prepare_declared_holdout_census_sha256(previous["census"])
        )
        expected_slacks.append(
            manifest["selected_at_utc"]
            - max(row["label_available_at_utc"] for row in previous["census"])
            - manifest["embargo_seconds"]
        )
    original = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_label_embargo_slack_seconds"] == min(expected_slacks)
    assert result["observation_count"] == 120
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result
    assert folds == original


@pytest.mark.parametrize("seed", range(16))
def test_randomized_late_label_one_second_past_embargo_rejected(seed):
    """Any row, not merely the final decision, can violate the next embargo."""
    import random

    rng = random.Random(20261028 + seed)
    folds = _valid()
    transition = rng.randrange(2)
    previous, later = folds[transition], folds[transition + 1]
    chosen = previous["census"][rng.randrange(len(previous["census"]))]
    chosen["label_available_at_utc"] = (
        later["manifest"]["selected_at_utc"] - later["manifest"]["embargo_seconds"] + 1
    )
    previous["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(previous["census"])
    )
    with pytest.raises(ValueError, match="labels not mature"):
        audit_declared_holdout_fold_isolation(folds)



@pytest.mark.parametrize("first_slack,second_slack,expected_later_index", [
    (3, 9, 1),
    (9, 3, 2),
    (3, 3, 1),  # Stable tie: first transition wins.
])
def test_tightest_declared_embargo_transition_is_traceable_and_stable(
    first_slack, second_slack, expected_later_index
):
    """Identify the weakest declared transition without accessing outcomes."""
    folds = _valid()
    for previous, later, slack in zip(
        folds, folds[1:], (first_slack, second_slack)
    ):
        # Earliest decision has the longest-maturing label, so the
        # diagnostic must use the maximum of all prior fold labels.
        previous["census"][0]["label_available_at_utc"] = (
            later["manifest"]["selected_at_utc"]
            - later["manifest"]["embargo_seconds"] - slack
        )
        previous["manifest"]["holdout_census_sha256"] = (
            prepare_declared_holdout_census_sha256(previous["census"])
        )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_label_embargo_slack_seconds"] == min(
        first_slack, second_slack
    )
    assert result["tightest_declared_label_embargo_later_fold_index"] == (
        expected_later_index
    )
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert result["holdout_untouched_independently_verified"] is False
    assert "net_cash" not in result
    assert folds == before


def test_interfold_selection_gap_tie_reports_earliest_later_fold():
    # Default synthetic two-year windows leave exactly seven days between
    # the previous declared holdout end and the next candidate selection.
    folds = _valid()
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_interfold_selection_gap_seconds"] == 7 * 86400
    assert result["tightest_declared_selection_gap_later_fold_index"] == 1
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result
    assert folds == before


@pytest.mark.parametrize("later_index,gap_seconds", [
    (1, 0), (1, 1), (2, 0), (2, 1),
])
def test_interfold_selection_gap_exact_boundary_and_one_second_violation(
    later_index, gap_seconds
):
    # A candidate selected at the exact prior-end boundary is permitted,
    # but one second earlier must fail, regardless of recommitted clocks.
    folds = _valid()
    later = folds[later_index]["manifest"]
    prior_end = folds[later_index - 1]["manifest"]["holdout_end_at_utc"]
    selected = prior_end + gap_seconds
    later["selected_at_utc"] = selected
    later["validation_end_at_utc"] = selected - later["embargo_seconds"]
    later["registered_at_utc"] = selected + 1
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["min_declared_interfold_selection_gap_seconds"] == gap_seconds
    assert result["tightest_declared_selection_gap_later_fold_index"] == later_index
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert result["profitable_edge_verified"] is False
    assert "net_cash" not in result
    assert folds == before

    later["selected_at_utc"] = prior_end - 1
    later["validation_end_at_utc"] = prior_end - 1 - later["embargo_seconds"]
    later["registered_at_utc"] = prior_end
    with pytest.raises(ValueError, match="candidate selection overlaps previous holdout"):
        audit_declared_holdout_fold_isolation(folds)
