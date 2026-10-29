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


def test_label_tail_diagnostic_zero_when_all_labels_mature_inside_windows():
    folds = _valid()
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["max_declared_label_tail_beyond_window_seconds"] == 0
    assert result["longest_declared_label_tail_fold_index"] is None
    for fold, summary in zip(folds, result["folds"]):
        assert summary["declared_label_tail_beyond_window_seconds"] == 0
        assert summary["latest_declared_label_available_at_utc"] == max(
            row["label_available_at_utc"] for row in fold["census"]
        )
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


@pytest.mark.parametrize("tail_seconds,expected_index", [
    (1, 0),
    (86400, 0),
    (2 * 86400, 2),
])
def test_declared_label_tail_reports_latest_maturity_not_last_decision(
    tail_seconds, expected_index
):
    folds = _valid()
    fold = folds[expected_index]
    # The earliest decision has the latest label; decision order is not
    # label-maturity order, and a one-second post-window tail is meaningful.
    fold["census"][0]["label_available_at_utc"] = (
        fold["manifest"]["holdout_end_at_utc"] + tail_seconds
    )
    fold["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(fold["census"])
    )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["max_declared_label_tail_beyond_window_seconds"] == tail_seconds
    assert result["longest_declared_label_tail_fold_index"] == expected_index
    assert result["folds"][expected_index]["declared_label_tail_beyond_window_seconds"] == tail_seconds
    assert result["folds"][expected_index]["latest_declared_label_available_at_utc"] == (
        fold["manifest"]["holdout_end_at_utc"] + tail_seconds
    )
    assert folds == before
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_equal_declared_label_tails_report_earliest_fold_without_outcomes():
    folds = _valid()
    for fold in folds[:2]:
        fold["census"][0]["label_available_at_utc"] = (
            fold["manifest"]["holdout_end_at_utc"] + 86400
        )
        fold["manifest"]["holdout_census_sha256"] = (
            prepare_declared_holdout_census_sha256(fold["census"])
        )
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["max_declared_label_tail_beyond_window_seconds"] == 86400
    assert result["longest_declared_label_tail_fold_index"] == 0
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_pending_label_population_zero_for_default_windows():
    folds = _valid()
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["total_declared_labels_pending_at_window_end_count"] == 0
    assert result["max_declared_labels_pending_at_window_end_count"] == 0
    assert result["most_pending_declared_labels_fold_index"] is None
    assert all(x["declared_labels_pending_at_window_end_count"] == 0
               for x in result["folds"])
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


@pytest.mark.parametrize("pending_count", [1, 2, 5, 40])
def test_pending_label_count_uses_every_row_and_exact_window_end_boundary(pending_count):
    folds = _valid()
    end = folds[2]["manifest"]["holdout_end_at_utc"]
    # The last fold has no subsequent selection. All observations remain
    # causal, but the outcomes become available one second after window end.
    for row in folds[2]["census"][:pending_count]:
        row["label_available_at_utc"] = end + 1
    folds[2]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[2]["census"])
    )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["folds"][2]["declared_labels_pending_at_window_end_count"] == pending_count
    assert result["total_declared_labels_pending_at_window_end_count"] == pending_count
    assert result["max_declared_labels_pending_at_window_end_count"] == pending_count
    assert result["most_pending_declared_labels_fold_index"] == 2
    assert result["max_declared_label_tail_beyond_window_seconds"] == 1
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result

    # Exactly at the window end is mature, not pending.
    folds[2]["census"][0]["label_available_at_utc"] = end
    folds[2]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[2]["census"])
    )
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["total_declared_labels_pending_at_window_end_count"] == pending_count - 1


def test_pending_label_count_stable_tie_and_study_total():
    folds = _valid()
    for index in (0, 2):
        end = folds[index]["manifest"]["holdout_end_at_utc"]
        # Nonmonotonic maturity: early decisions remain pending.
        for row in folds[index]["census"][:3]:
            row["label_available_at_utc"] = end + 1
        folds[index]["manifest"]["holdout_census_sha256"] = (
            prepare_declared_holdout_census_sha256(folds[index]["census"])
        )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["total_declared_labels_pending_at_window_end_count"] == 6
    assert result["max_declared_labels_pending_at_window_end_count"] == 3
    assert result["most_pending_declared_labels_fold_index"] == 0
    assert [x["declared_labels_pending_at_window_end_count"]
            for x in result["folds"]] == [3, 0, 3]
    assert folds == before
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_declared_validation_cutoff_availability_is_zero_for_default_windows():
    folds = _valid()
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["declared_validation_cutoff_transitions"] == [
        {"later_fold_index": 1,
         "declared_prior_labels_unavailable_at_validation_end_count": 0,
         "declared_all_prior_labels_unavailable_at_validation_end_count": 0},
        {"later_fold_index": 2,
         "declared_prior_labels_unavailable_at_validation_end_count": 0,
         "declared_all_prior_labels_unavailable_at_validation_end_count": 0},
    ]
    assert result["total_declared_prior_labels_unavailable_at_validation_end_count"] == 0
    assert result["max_declared_prior_labels_unavailable_at_validation_end_count"] == 0
    assert result["most_unavailable_at_validation_later_fold_index"] is None
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


@pytest.mark.parametrize("later_index", [1, 2])
def test_prior_label_validation_cutoff_equality_vs_one_second_late(later_index):
    folds = _valid()
    previous, later = folds[later_index - 1], folds[later_index]
    cutoff = later["manifest"]["validation_end_at_utc"]
    previous["census"][0]["label_available_at_utc"] = cutoff
    previous["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(previous["census"])
    )
    assert audit_declared_holdout_fold_isolation(folds)[
        "declared_validation_cutoff_transitions"
    ][later_index - 1]["declared_prior_labels_unavailable_at_validation_end_count"] == 0

    previous["census"][0]["label_available_at_utc"] = cutoff + 1
    previous["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(previous["census"])
    )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["declared_validation_cutoff_transitions"][later_index - 1][
        "declared_prior_labels_unavailable_at_validation_end_count"
    ] == 1
    assert result["total_declared_prior_labels_unavailable_at_validation_end_count"] == 1
    assert result["most_unavailable_at_validation_later_fold_index"] == later_index
    # A label can miss validation yet satisfy the later selection embargo.
    assert result["min_declared_label_embargo_slack_seconds"] >= 0
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert folds == before
    assert "net_cash" not in result


@pytest.mark.parametrize("unavailable_count", [1, 2, 5])
def test_validation_cutoff_population_counts_all_previous_rows(unavailable_count):
    folds = _valid()
    previous, later = folds[1], folds[2]
    cutoff = later["manifest"]["validation_end_at_utc"]
    for row in previous["census"][:unavailable_count]:
        row["label_available_at_utc"] = cutoff + 1
    previous["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(previous["census"])
    )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["declared_validation_cutoff_transitions"][-1][
        "declared_prior_labels_unavailable_at_validation_end_count"
    ] == unavailable_count
    assert result["total_declared_prior_labels_unavailable_at_validation_end_count"] == unavailable_count
    assert result["max_declared_prior_labels_unavailable_at_validation_end_count"] == unavailable_count
    assert result["most_unavailable_at_validation_later_fold_index"] == 2
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_validation_cutoff_population_tie_selects_earliest_later_fold():
    folds = _valid()
    for previous, later in zip(folds, folds[1:]):
        cutoff = later["manifest"]["validation_end_at_utc"]
        for row in previous["census"][:3]:
            row["label_available_at_utc"] = cutoff + 1
        previous["manifest"]["holdout_census_sha256"] = (
            prepare_declared_holdout_census_sha256(previous["census"])
        )
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert [t["declared_prior_labels_unavailable_at_validation_end_count"]
            for t in result["declared_validation_cutoff_transitions"]] == [3, 3]
    assert result["total_declared_prior_labels_unavailable_at_validation_end_count"] == 6
    assert result["max_declared_prior_labels_unavailable_at_validation_end_count"] == 3
    assert result["most_unavailable_at_validation_later_fold_index"] == 1
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_validation_cutoff_can_precede_prior_window_end_without_claiming_leakage():
    folds = _valid()
    previous, later = folds[0], folds[1]
    previous_end = previous["manifest"]["holdout_end_at_utc"]
    later["manifest"]["validation_end_at_utc"] = previous_end - 1
    previous["census"][0]["label_available_at_utc"] = previous_end
    previous["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(previous["census"])
    )
    result = audit_declared_holdout_fold_isolation(folds)
    assert result["declared_validation_cutoff_transitions"][0][
        "declared_prior_labels_unavailable_at_validation_end_count"
    ] == 1
    assert result["min_declared_label_embargo_slack_seconds"] >= 0
    assert result["source_bytes_independently_authenticated"] is False
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_declared_decision_coverage_exposes_early_concentration_without_outcomes():
    # Forty daily decisions occupy only 39 days of each declared two-year
    # window. This does not prove that later source candles are missing.
    folds = _valid()
    original = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    expected_gaps = []
    for index, fold in enumerate(folds):
        census, manifest = fold["census"], fold["manifest"]
        summary = report["folds"][index]
        first, last = census[0]["decision_at_utc"], census[-1]["decision_at_utc"]
        gap = manifest["holdout_end_at_utc"] - last
        expected_gaps.append(gap)
        assert summary["first_declared_decision_at_utc"] == first
        assert summary["last_declared_decision_at_utc"] == last
        assert summary["declared_decision_span_seconds"] == 39 * 86400
        assert summary["max_declared_interdecision_gap_seconds"] == 86400
        assert summary["declared_last_decision_to_window_end_seconds"] == gap
    assert report["max_declared_last_decision_to_window_end_seconds"] == max(expected_gaps)
    assert report["longest_declared_last_decision_gap_fold_index"] == (
        expected_gaps.index(max(expected_gaps))
    )
    assert folds == original
    assert report["profitable_edge_verified"] is False
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False
    assert "net_cash" not in report


def test_single_observation_fold_has_no_interdecision_gap():
    folds = _valid()
    last = folds[2]
    last["census"] = last["census"][:1]
    last["manifest"]["expected_holdout_count"] = 1
    last["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(last["census"])
    )
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    assert report["folds"][2]["declared_decision_span_seconds"] == 0
    assert report["folds"][2]["max_declared_interdecision_gap_seconds"] is None
    assert report["folds"][2]["declared_last_decision_to_window_end_seconds"] == (
        last["manifest"]["holdout_end_at_utc"] - last["census"][0]["decision_at_utc"]
    )
    assert report["observation_count"] == 81
    assert folds == before
    assert report["may_execute_real_order"] is False


def test_late_final_fold_decision_updates_gap_without_rewriting_inputs():
    folds = _valid()
    final = folds[-1]
    end = final["manifest"]["holdout_end_at_utc"]
    final["census"][-1]["decision_at_utc"] = end - 2
    final["census"][-1]["label_available_at_utc"] = end + 2
    final["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(final["census"])
    )
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    summary = report["folds"][-1]
    assert summary["last_declared_decision_at_utc"] == end - 2
    assert summary["declared_last_decision_to_window_end_seconds"] == 2
    assert summary["declared_labels_pending_at_window_end_count"] == 1
    assert summary["max_declared_interdecision_gap_seconds"] > 86400
    assert folds == before
    assert report["source_bytes_independently_authenticated"] is False
    assert report["holdout_untouched_independently_verified"] is False
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False


def _place_decisions_on_quarter_boundaries(fold, count):
    """Synthetic exact half-open quarter boundaries; not market coverage."""
    manifest = fold["manifest"]
    start = manifest["holdout_start_at_utc"]
    duration = manifest["holdout_end_at_utc"] - start
    fold["census"] = fold["census"][:count]
    for quarter, row in enumerate(fold["census"]):
        # Ceiling ensures exact quarter assignment for non-divisible durations.
        decision = start + (quarter * duration + 3) // 4
        row["decision_at_utc"] = decision
        row["label_available_at_utc"] = decision + 1
    manifest["expected_holdout_count"] = count
    manifest["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(fold["census"])
    )


def test_declared_decision_quarter_counts_expose_early_concentration():
    folds = _valid()
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert [x["declared_decision_quarter_counts"] for x in result["folds"]] == [
        [40, 0, 0, 0], [40, 0, 0, 0], [40, 0, 0, 0]
    ]
    assert result["min_declared_nonempty_decision_quarter_count"] == 1
    assert result["sparsest_declared_decision_quarters_fold_index"] == 0
    assert folds == before
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


@pytest.mark.parametrize("active_quarters", [1, 2, 3, 4])
def test_declared_decision_quarter_exact_boundaries(active_quarters):
    folds = _valid()
    _place_decisions_on_quarter_boundaries(folds[2], active_quarters)
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    summary = result["folds"][2]
    assert summary["declared_decision_quarter_counts"] == (
        [1] * active_quarters + [0] * (4 - active_quarters)
    )
    assert summary["declared_nonempty_decision_quarter_count"] == active_quarters
    assert sum(summary["declared_decision_quarter_counts"]) == active_quarters
    assert folds == before
    assert result["profitable_edge_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def test_declared_decision_quarter_study_minimum_selects_sparse_final_fold():
    folds = _valid()
    for fold in folds[:2]:
        _place_decisions_on_quarter_boundaries(fold, 4)
    _place_decisions_on_quarter_boundaries(folds[2], 1)
    before = copy.deepcopy(folds)
    result = audit_declared_holdout_fold_isolation(folds)
    assert [x["declared_nonempty_decision_quarter_count"] for x in result["folds"]] == [4, 4, 1]
    assert result["min_declared_nonempty_decision_quarter_count"] == 1
    assert result["sparsest_declared_decision_quarters_fold_index"] == 2
    assert folds == before
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_real_order"] is False
    assert "net_cash" not in result


def _set_declared_quarter_population(fold, counts):
    """Build ordered, unique synthetic decisions; no price or outcome data."""
    assert len(counts) == 4 and all(type(n) is int and n >= 0 for n in counts)
    assert sum(counts) > 0
    manifest = fold["manifest"]
    start = manifest["holdout_start_at_utc"]
    duration = manifest["holdout_end_at_utc"] - start
    template = fold["census"][0]
    rows = []
    for quarter, count in enumerate(counts):
        quarter_start = start + (quarter * duration + 3) // 4
        for offset in range(count):
            decision = quarter_start + offset + 1
            assert 4 * (decision - start) // duration == quarter
            row = copy.deepcopy(template)
            row["observation_id"] = f"synthetic-quarter-{len(rows):04d}"
            row["row_sha256"] = f"{int(template['source_sha256'], 16) * 1000000 + 200000 + len(rows):064x}"
            row["decision_at_utc"] = decision
            row["label_available_at_utc"] = decision + 1
            rows.append(row)
    fold["census"] = rows
    manifest["expected_holdout_count"] = len(rows)
    manifest["holdout_census_sha256"] = prepare_declared_holdout_census_sha256(rows)


@pytest.mark.parametrize("counts, expected_bp", [
    ([97, 1, 1, 1], 9700),
    ([25, 25, 25, 25], 2500),
    ([2, 1, 1, 1], 4000),
    ([1, 1, 1, 1], 2500),
])
def test_largest_quarter_share_distinguishes_all_quarters_active(counts, expected_bp):
    folds = _valid()
    _set_declared_quarter_population(folds[-1], counts)
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    summary = report["folds"][-1]
    assert summary["declared_decision_quarter_counts"] == counts
    assert summary["declared_nonempty_decision_quarter_count"] == 4
    assert summary["declared_largest_quarter_decision_share_basis_points"] == expected_bp
    assert report["max_declared_largest_quarter_decision_share_basis_points"] == 10000
    assert report["most_concentrated_quarter_fold_index"] == 0
    assert folds == before
    assert report["source_bytes_independently_authenticated"] is False
    assert report["holdout_untouched_independently_verified"] is False
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False
    assert "net_cash" not in report


def test_study_concentration_selects_later_fold_when_earlier_folds_balanced():
    folds = _valid()
    for fold in folds[:2]:
        _set_declared_quarter_population(fold, [1, 1, 1, 1])
    _set_declared_quarter_population(folds[2], [97, 1, 1, 1])
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    assert [f["declared_largest_quarter_decision_share_basis_points"]
            for f in report["folds"]] == [2500, 2500, 9700]
    assert report["max_declared_largest_quarter_decision_share_basis_points"] == 9700
    assert report["most_concentrated_quarter_fold_index"] == 2
    assert folds == before
    assert report["may_execute_real_order"] is False


def test_study_concentration_equal_share_tie_uses_earliest_fold():
    folds = _valid()
    for fold in folds[:2]:
        _set_declared_quarter_population(fold, [97, 1, 1, 1])
    _set_declared_quarter_population(folds[2], [25, 25, 25, 25])
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    assert report["max_declared_largest_quarter_decision_share_basis_points"] == 9700
    assert report["most_concentrated_quarter_fold_index"] == 0
    assert folds == before
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False


@pytest.mark.parametrize("cutoff_kind, expected_all_prior", [
    ("before_first_fold_final_label", 41),
    ("at_first_fold_final_label", 40),
    ("before_second_fold_first_label", 40),
    ("at_second_fold_final_label", 0),
])
def test_all_earlier_fold_labels_counted_at_later_validation_cutoff(
    cutoff_kind, expected_all_prior
):
    # The final fold's validation cutoff may precede earlier holdouts,
    # despite a later selection satisfying every prior-label embargo.
    folds = _valid()
    first, second = folds[0]["census"], folds[1]["census"]
    cutoffs = {
        "before_first_fold_final_label": first[-1]["label_available_at_utc"] - 1,
        "at_first_fold_final_label": first[-1]["label_available_at_utc"],
        "before_second_fold_first_label": second[0]["label_available_at_utc"] - 1,
        "at_second_fold_final_label": second[-1]["label_available_at_utc"],
    }
    folds[2]["manifest"]["validation_end_at_utc"] = cutoffs[cutoff_kind]
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    transition = report["declared_validation_cutoff_transitions"][-1]
    immediate = sum(
        row["label_available_at_utc"] > cutoffs[cutoff_kind] for row in second
    )
    assert transition["declared_prior_labels_unavailable_at_validation_end_count"] == immediate
    assert transition[
        "declared_all_prior_labels_unavailable_at_validation_end_count"
    ] == expected_all_prior
    assert report["total_declared_all_prior_labels_unavailable_at_validation_end_count"] == (
        expected_all_prior
    )
    assert report["max_declared_all_prior_labels_unavailable_at_validation_end_count"] == (
        expected_all_prior
    )
    assert report["most_all_prior_unavailable_at_validation_later_fold_index"] == (
        2 if expected_all_prior else None
    )
    assert folds == before
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False
    assert "net_cash" not in report


def test_all_prior_validation_population_tie_prefers_earliest_later_fold():
    folds = [_fold(i) for i in range(4)]
    # At fold 2, both earlier folds are unavailable at the old cutoff:
    # 40 + 40 = 80. At fold 3, fold 0 is mature, but folds 1 and 2
    # each still have 40 labels unavailable, producing an exact tie.
    folds[2]["manifest"]["validation_end_at_utc"] = (
        folds[0]["census"][0]["label_available_at_utc"] - 1
    )
    folds[3]["manifest"]["validation_end_at_utc"] = (
        folds[1]["census"][0]["label_available_at_utc"] - 1
    )
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    counts = [
        transition["declared_all_prior_labels_unavailable_at_validation_end_count"]
        for transition in report["declared_validation_cutoff_transitions"]
    ]
    assert counts == [0, 80, 80]
    assert report["total_declared_all_prior_labels_unavailable_at_validation_end_count"] == 160
    assert report["max_declared_all_prior_labels_unavailable_at_validation_end_count"] == 80
    assert report["most_all_prior_unavailable_at_validation_later_fold_index"] == 2
    assert folds == before
    assert report["holdout_untouched_independently_verified"] is False
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False


def test_maximum_24_disjoint_two_year_folds_remain_membership_only():
    # 48 declared synthetic years, 960 unique observations, no market data.
    folds = [_fold(i) for i in range(24)]
    before = copy.deepcopy(folds)
    report = audit_declared_holdout_fold_isolation(folds)
    assert report["fold_count"] == 24
    assert report["observation_count"] == 24 * 40
    assert len(report["declared_validation_cutoff_transitions"]) == 23
    assert len({f["archive_sha256"] for f in report["folds"]}) == 24
    assert sum(sum(f["declared_decision_quarter_counts"]) for f in report["folds"]) == 960
    assert report["total_declared_all_prior_labels_unavailable_at_validation_end_count"] == 0
    assert folds == before
    assert report["source_bytes_independently_authenticated"] is False
    assert report["holdout_untouched_independently_verified"] is False
    assert report["profitable_edge_verified"] is False
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False
    assert "net_cash" not in report


def test_more_than_24_declared_folds_rejected_before_research():
    with pytest.raises(ValueError, match="2..24"):
        audit_declared_holdout_fold_isolation([_fold(i) for i in range(25)])


@pytest.mark.parametrize("field, replacement", [
    ("provider", "AnotherSyntheticProvider"),
    ("venue", "AnotherOfflineVenue"),
    ("instrument", "WTIUSD-CFD"),
    ("quote_side", "ASK"),
    ("account_alias", "different-paper-account"),
    ("settlement_currency", "USD"),
])
def test_last_of_24_folds_cannot_change_source_convention(field, replacement):
    folds = [_fold(i) for i in range(24)]
    folds[-1]["manifest"]["source"][field] = replacement
    with pytest.raises(ValueError, match="Cross-fold study/candidate/source"):
        audit_declared_holdout_fold_isolation(folds)


def test_last_of_24_folds_rejects_cross_archive_row_identity_reuse():
    folds = [_fold(i) for i in range(24)]
    folds[-1]["census"][0]["row_sha256"] = folds[0]["census"][0]["row_sha256"]
    folds[-1]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[-1]["census"])
    )
    with pytest.raises(ValueError, match="Cross-fold row identity reused"):
        audit_declared_holdout_fold_isolation(folds)


def test_last_of_24_folds_rejects_immature_prior_label_even_with_recommitted_census():
    folds = [_fold(i) for i in range(24)]
    # An otherwise valid prior fold declares a late-maturing last label.
    # Recomputing its caller-controlled digest must not bypass embargo.
    folds[-2]["census"][-1]["label_available_at_utc"] = (
        folds[-1]["manifest"]["selected_at_utc"]
    )
    folds[-2]["manifest"]["holdout_census_sha256"] = (
        prepare_declared_holdout_census_sha256(folds[-2]["census"])
    )
    with pytest.raises(ValueError, match="labels not mature"):
        audit_declared_holdout_fold_isolation(folds)
