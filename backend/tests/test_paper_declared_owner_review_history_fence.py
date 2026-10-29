"""Synthetic, non-executing tests for declared owner review history continuity."""
from copy import deepcopy
import pytest

from app.paper_declared_owner_review_history_fence import inspect_declared_owner_review_history_fence

NOW = 1_800_000_000_000


def event(n=1, decision="APPROVE"):
    return dict(approval_id=f"review{n}", client_order_id=f"order{n}",
                order_intent_sha=f"{n:064x}", preview_digest=f"{n+10:064x}",
                decision=decision, issued_at_ms=NOW-350+n*10,
                expires_at_ms=NOW+1_000+n*10, recorded_at_ms=NOW-350+n*10)


def snapshots():
    previous = dict(broker="PAPER-LOCAL", account_alias="demo", session_id="session1",
                    sequence=3, observed_at_ms=NOW-100, events=[event(1)])
    current = deepcopy(previous)
    # The prior snapshot must precede the newly appended review record.
    previous["observed_at_ms"] = NOW - 335
    current["sequence"] = 4
    current["events"].append(event(2))
    return previous, current


def inspect(previous=None, current=None):
    if current is None:
        previous, current = snapshots()
    return inspect_declared_owner_review_history_fence(previous, current, NOW)


def test_clean_append_is_still_unverified_and_nonexecuting():
    result = inspect()
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["appended_events"] == 1
    for field in ("history_authenticated", "independent_audit_anchor_verified",
                  "owner_identity_authenticated", "approval_signature_verified",
                  "approval_nonce_atomically_consumed", "may_submit_paper_order", "may_submit_real_order"):
        assert result[field] is False


def test_missing_previous_history_holds():
    _, curr = snapshots()
    assert "missing_independent_prior_history" in inspect(None, curr)["failed_checks"]


def test_repeat_snapshot_allowed_without_authorization():
    prev, _ = snapshots()
    assert inspect(prev, deepcopy(prev))["failed_checks"] == []


@pytest.mark.parametrize("mutation,check", [
    (lambda p,c: c.update(events=[]), "history_rewritten_or_truncated"),
    (lambda p,c: c["events"][0].update(decision="REJECT"), "history_rewritten_or_truncated"),
    (lambda p,c: c.update(sequence=3), "history_revision_not_advanced_once"),
    (lambda p,c: c.update(sequence=5), "history_revision_not_advanced_once"),
    (lambda p,c: c.update(sequence=2), "history_revision_rollback"),
    (lambda p,c: c.update(session_id="session2"), "session_change_requires_external_reconciliation"),
    (lambda p,c: c.update(account_alias="other"), "broker_account_changed"),
    (lambda p,c: c.update(observed_at_ms=p["observed_at_ms"]-1), "snapshot_time_rollback"),
    (lambda p,c: c["events"][1].update(approval_id="review1"), "duplicate_approval_id"),
    (lambda p,c: c["events"][1].update(client_order_id="order1"), "duplicate_approved_order_or_intent"),
    (lambda p,c: c["events"][1].update(order_intent_sha=p["events"][0]["order_intent_sha"]), "duplicate_approved_order_or_intent"),
    (lambda p,c: c["events"][1].update(recorded_at_ms=p["events"][0]["recorded_at_ms"]), "non_monotonic_review_recording"),
    (lambda p,c: c["events"][1].update(expires_at_ms=NOW-1000), "invalid_review_lifetime"),
    (lambda p,c: c["events"][1].update(recorded_at_ms=NOW+1), "invalid_review_event_chronology"),
    (lambda p,c: c.update(observed_at_ms=NOW+1), "current_snapshot_stale_or_future"),
    (lambda p,c: c.update(observed_at_ms=NOW-30_001), "current_snapshot_stale_or_future"),
])
def test_fail_closed_changes(mutation, check):
    prev, curr = snapshots()
    mutation(prev, curr)
    result = inspect(prev, curr)
    assert check in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"
    assert result["may_submit_real_order"] is False


def test_rejection_then_approval_same_intent_holds():
    prev, curr = snapshots()
    prev["events"][0]["decision"] = "REJECT"
    curr["events"][0]["decision"] = "REJECT"
    curr["events"][1]["order_intent_sha"] = prev["events"][0]["order_intent_sha"]
    assert "approval_after_rejection_same_intent" in inspect(prev, curr)["failed_checks"]


def test_approval_recorded_at_expiry_holds():
    prev, curr = snapshots()
    curr["events"][1]["expires_at_ms"] = curr["events"][1]["recorded_at_ms"]
    assert "approval_recorded_after_expiry" in inspect(prev, curr)["failed_checks"]


def test_no_append_cannot_increase_revision():
    prev, curr = snapshots()
    curr["events"] = deepcopy(prev["events"])
    assert "revision_changed_without_append" in inspect(prev, curr)["failed_checks"]


def test_non_mutating_and_stable_digest():
    prev, curr = snapshots()
    originals = deepcopy((prev, curr))
    a = inspect(prev, curr)
    assert (prev, curr) == originals
    curr = dict(reversed(list(curr.items())))
    assert inspect(prev, curr)["current_history_digest"] == a["current_history_digest"]


@pytest.mark.parametrize("edit", [
    lambda c: c.update(sequence=True),
    lambda c: c.update(events="not-a-list"),
    lambda c: c["events"][0].update(decision="UNKNOWN"),
    lambda c: c["events"][0].update(preview_digest="not-sha"),
    lambda c: c["events"][0].update(issued_at_ms=True),
    lambda c: c["events"][0].update(extra="bad"),
    lambda c: c.update(extra="bad"),
])
def test_invalid_schemas_rejected(edit):
    prev, curr = snapshots()
    edit(curr)
    with pytest.raises(ValueError):
        inspect(prev, curr)


def test_old_prior_checkpoint_does_not_false_hold_fresh_current():
    prev, curr = snapshots()
    prev["observed_at_ms"] = NOW - 120_000
    prev["events"][0].update(issued_at_ms=NOW-121_000,
                             expires_at_ms=NOW-119_000, recorded_at_ms=NOW-120_500)
    curr["events"][0] = deepcopy(prev["events"][0])
    assert inspect(prev, curr)["failed_checks"] == []

def test_future_prior_checkpoint_holds():
    prev, curr = snapshots()
    prev["observed_at_ms"] = NOW + 1
    assert "previous_snapshot_stale_or_future" in inspect(prev, curr)["failed_checks"]


def test_rejected_client_order_cannot_be_reapproved_with_new_intent():
    prev, curr = snapshots()
    prev["events"][0]["decision"] = "REJECT"
    curr["events"][0]["decision"] = "REJECT"
    curr["events"][1]["client_order_id"] = prev["events"][0]["client_order_id"]
    result = inspect(prev, curr)
    assert "approval_after_rejection_same_client_order" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"
    assert result["may_submit_real_order"] is False


def test_rejection_after_approval_same_client_order_holds():
    prev, curr = snapshots()
    curr["events"][1]["decision"] = "REJECT"
    curr["events"][1]["client_order_id"] = prev["events"][0]["client_order_id"]
    result = inspect(prev, curr)
    assert "rejection_after_approval_same_order_or_intent" in result["failed_checks"]
    assert result["may_submit_paper_order"] is False


def test_rejection_after_approval_same_intent_holds():
    prev, curr = snapshots()
    curr["events"][1]["decision"] = "REJECT"
    curr["events"][1]["order_intent_sha"] = prev["events"][0]["order_intent_sha"]
    assert "rejection_after_approval_same_order_or_intent" in inspect(prev, curr)["failed_checks"]


def test_unrelated_rejection_after_approval_is_not_a_false_hold():
    prev, curr = snapshots()
    curr["events"][1]["decision"] = "REJECT"
    result = inspect(prev, curr)
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_unrelated_approval_after_rejection_is_not_a_false_hold():
    prev, curr = snapshots()
    prev["events"][0]["decision"] = "REJECT"
    curr["events"][0]["decision"] = "REJECT"
    result = inspect(prev, curr)
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_contradictory_review_does_not_mutate_input():
    prev, curr = snapshots()
    curr["events"][1]["decision"] = "REJECT"
    curr["events"][1]["client_order_id"] = prev["events"][0]["client_order_id"]
    before = deepcopy((prev, curr))
    assert "rejection_after_approval_same_order_or_intent" in inspect(prev, curr)["failed_checks"]
    assert (prev, curr) == before


def _two_rejections():
    prev, curr = snapshots()
    prev["events"][0]["decision"] = "REJECT"
    curr["events"][0]["decision"] = "REJECT"
    curr["events"][1]["decision"] = "REJECT"
    return prev, curr


def test_duplicate_rejection_same_client_order_and_intent_holds():
    prev, curr = _two_rejections()
    curr["events"][1]["client_order_id"] = prev["events"][0]["client_order_id"]
    curr["events"][1]["order_intent_sha"] = prev["events"][0]["order_intent_sha"]
    curr["events"][1]["preview_digest"] = prev["events"][0]["preview_digest"]
    result = inspect(prev, curr)
    assert "duplicate_rejected_order_or_intent" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"
    assert result["may_submit_real_order"] is False


def test_rejected_client_order_cannot_be_rebound_to_new_intent():
    prev, curr = _two_rejections()
    curr["events"][1]["client_order_id"] = prev["events"][0]["client_order_id"]
    result = inspect(prev, curr)
    assert "client_order_rebound_to_different_intent" in result["failed_checks"]
    assert result["may_submit_paper_order"] is False


def test_rejected_intent_cannot_be_rebound_to_new_client_order():
    prev, curr = _two_rejections()
    curr["events"][1]["order_intent_sha"] = prev["events"][0]["order_intent_sha"]
    result = inspect(prev, curr)
    assert "order_intent_rebound_to_different_client_order" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_preview_digest_reuse_for_different_order_holds():
    prev, curr = snapshots()
    curr["events"][1]["preview_digest"] = prev["events"][0]["preview_digest"]
    result = inspect(prev, curr)
    assert "preview_digest_reused_for_distinct_order" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"


def test_unrelated_rejections_remain_unverified_without_false_hold():
    prev, curr = _two_rejections()
    result = inspect(prev, curr)
    assert result["failed_checks"] == []
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_identity_rebinding_check_does_not_mutate_inputs():
    prev, curr = _two_rejections()
    curr["events"][1]["client_order_id"] = prev["events"][0]["client_order_id"]
    originals = deepcopy((prev, curr))
    assert "client_order_rebound_to_different_intent" in inspect(prev, curr)["failed_checks"]
    assert (prev, curr) == originals


def test_backfilled_review_before_prior_snapshot_holds():
    prev, curr = snapshots()
    curr["events"][1]["recorded_at_ms"] = prev["observed_at_ms"]
    result = inspect(prev, curr)
    assert "appended_review_predates_prior_snapshot" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_backfilled_review_strictly_older_than_prior_snapshot_holds():
    prev, curr = snapshots()
    curr["events"][1]["recorded_at_ms"] = prev["observed_at_ms"] - 1
    result = inspect(prev, curr)
    assert "appended_review_predates_prior_snapshot" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"


def test_recorded_after_prior_snapshot_does_not_false_hold():
    prev, curr = snapshots()
    curr["events"][1]["recorded_at_ms"] = prev["observed_at_ms"] + 1
    curr["events"][1]["issued_at_ms"] = prev["observed_at_ms"] + 1
    assert inspect(prev, curr)["failed_checks"] == []


def test_two_appended_reviews_in_one_revision_hold():
    prev, curr = snapshots()
    curr["events"].append(event(3))
    result = inspect(prev, curr)
    assert "multiple_reviews_appended_in_single_revision" in result["failed_checks"]
    assert result["appended_events"] == 2
    assert result["may_submit_paper_order"] is False


def test_batch_append_still_holds_with_extra_revision_jump():
    prev, curr = snapshots()
    curr["events"].append(event(3))
    curr["sequence"] += 1
    result = inspect(prev, curr)
    assert "multiple_reviews_appended_in_single_revision" in result["failed_checks"]
    assert "history_revision_not_advanced_once" in result["failed_checks"]


def test_backfill_hold_does_not_mutate_inputs():
    prev, curr = snapshots()
    curr["events"][1]["recorded_at_ms"] = prev["observed_at_ms"]
    before = deepcopy((prev, curr))
    assert "appended_review_predates_prior_snapshot" in inspect(prev, curr)["failed_checks"]
    assert (prev, curr) == before


def test_current_history_population_cannot_exceed_revision():
    prev, curr = snapshots()
    curr["sequence"] = 1  # Two events cannot fit in one revision.
    result = inspect(prev, curr)
    assert "history_population_exceeds_revision" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"
    assert result["may_submit_real_order"] is False


def test_prior_history_population_cannot_exceed_revision():
    prev, curr = snapshots()
    prev["sequence"] = 0  # Even an old checkpoint must be internally consistent.
    result = inspect(prev, curr)
    assert "history_population_exceeds_revision" in result["failed_checks"]
    assert result["may_submit_paper_order"] is False


def test_revision_population_boundary_is_not_false_hold():
    prev, curr = snapshots()
    prev["sequence"] = 1
    curr["sequence"] = 2
    result = inspect(prev, curr)
    assert result["failed_checks"] == []
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_zero_revision_empty_history_is_consistent_but_unverified():
    prev, curr = snapshots()
    prev["events"] = []
    curr["events"] = []
    prev["sequence"] = 0
    curr["sequence"] = 0
    result = inspect(prev, curr)
    assert result["failed_checks"] == []
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_paper_order"] is False


def test_revision_population_hold_does_not_mutate_snapshots():
    prev, curr = snapshots()
    curr["sequence"] = 1
    original = deepcopy((prev, curr))
    assert "history_population_exceeds_revision" in inspect(prev, curr)["failed_checks"]
    assert (prev, curr) == original


def test_appended_review_issued_at_prior_snapshot_holds():
    prev, curr = snapshots()
    curr["events"][1]["issued_at_ms"] = prev["observed_at_ms"]
    result = inspect(prev, curr)
    assert "appended_review_issued_before_prior_snapshot" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_appended_review_issued_before_prior_snapshot_holds():
    prev, curr = snapshots()
    curr["events"][1]["issued_at_ms"] = prev["observed_at_ms"] - 1
    result = inspect(prev, curr)
    assert "appended_review_issued_before_prior_snapshot" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"


def test_appended_review_issued_after_prior_snapshot_is_not_false_hold():
    prev, curr = snapshots()
    curr["events"][1]["issued_at_ms"] = prev["observed_at_ms"] + 1
    assert inspect(prev, curr)["failed_checks"] == []


def test_issued_time_hold_does_not_mutate_inputs():
    prev, curr = snapshots()
    curr["events"][1]["issued_at_ms"] = prev["observed_at_ms"]
    original = deepcopy((prev, curr))
    assert "appended_review_issued_before_prior_snapshot" in inspect(prev, curr)["failed_checks"]
    assert (prev, curr) == original


@pytest.mark.parametrize("expires", [NOW - 1, NOW])
def test_new_approval_expired_by_evaluation_holds(expires):
    prev, curr = snapshots()
    curr["events"][1]["expires_at_ms"] = expires
    result = inspect(prev, curr)
    assert "appended_approval_expired_at_evaluation" in result["failed_checks"]
    assert result["status"] == "HOLD_DECLARED_REVIEW_HISTORY"
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False


def test_new_approval_expires_after_evaluation_is_still_unverified():
    prev, curr = snapshots()
    curr["events"][1]["expires_at_ms"] = NOW + 1
    result = inspect(prev, curr)
    assert result["failed_checks"] == []
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_expired_historical_approval_does_not_block_unrelated_rejection():
    prev, curr = snapshots()
    prev["events"][0]["expires_at_ms"] = NOW - 200
    curr["events"][0]["expires_at_ms"] = NOW - 200
    curr["events"][1]["decision"] = "REJECT"
    result = inspect(prev, curr)
    assert result["failed_checks"] == []
    assert result["status"] == "DECLARED_REVIEW_HISTORY_UNVERIFIED"
    assert result["may_submit_paper_order"] is False


def test_expired_new_approval_check_does_not_mutate_history():
    prev, curr = snapshots()
    curr["events"][1]["expires_at_ms"] = NOW
    original = deepcopy((prev, curr))
    assert "appended_approval_expired_at_evaluation" in inspect(prev, curr)["failed_checks"]
    assert (prev, curr) == original
