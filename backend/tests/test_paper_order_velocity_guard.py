"""Deterministic synthetic checks. No broker connectivity or execution."""
from copy import deepcopy
import pytest
from app.paper_order_velocity_guard import review_paper_order_velocity as review

NOW = 1_800_000_000_000
HOUR = 3_600_000
DAY = 86_400_000


def fixture():
    return (
        dict(account_id="paper-account-001", client_order_id="client-order-999",
             instrument="XAUUSD", intent_sha256="f" * 64, side="BUY"),
        dict(account_id="paper-account-001", coverage_started_at_ms=NOW-DAY-100,
             snapshot_at_ms=NOW-100, first_sequence=1, events=[]),
        dict(max_attempts_per_hour=5, max_symbol_attempts_per_hour=3,
             max_attempts_utc_day=20, same_symbol_cooldown_ms=60000,
             max_symbol_side_flips_per_hour=1, max_history_snapshot_age_ms=3000,
             emergency_latched=False, daily_loss_latched=False),
    )


def event(i, *, ms=None, symbol="XAUUSD", side="BUY", state="CLOSED", digest=None):
    return dict(client_order_id=f"client-order-{i:03d}", instrument=symbol,
                intent_sha256=digest or f"{i:064x}", side=side, state=state,
                sequence=i, attempted_at_ms=NOW-HOUR+1000*i if ms is None else ms)


def test_clean_empty_declared_history_never_authorizes_execution():
    c,h,p = fixture(); result = review(c,h,p,now_ms=NOW)
    assert result["status"] == "ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED"
    assert not result["may_execute_real_order"] and not result["may_execute_paper_order"]
    assert not result["history_authenticated"] and not result["human_approval_recorded"]


def test_hourly_attempt_cap_counts_rejected_attempts():
    c,h,p = fixture(); h["events"] = [event(i, symbol="EURUSD", state="REJECTED") for i in range(1,6)]
    assert "hourly_attempt_cap" in review(c,h,p,now_ms=NOW)["failed_checks"]


def test_symbol_cap_and_cooldown():
    c,h,p = fixture(); h["events"] = [event(i) for i in range(1,4)]
    assert "symbol_hourly_attempt_cap" in review(c,h,p,now_ms=NOW)["failed_checks"]
    h["events"] = [event(1,ms=NOW-100)]
    assert "same_symbol_cooldown_elapsed" in review(c,h,p,now_ms=NOW)["failed_checks"]


def test_utc_day_cap_counts_prior_hour_attempts():
    c,h,p = fixture(); p["max_attempts_utc_day"] = 2
    # Last two attempts are within UTC day for this synthetic timestamp.
    h["events"] = [event(1,ms=NOW-10000),event(2,ms=NOW-9000)]
    assert "utc_daily_attempt_cap" in review(c,h,p,now_ms=NOW)["failed_checks"]


@pytest.mark.parametrize("state", ["PENDING", "CANCEL_REQUESTED", "OUTCOME_UNKNOWN"])
def test_uncertain_outcomes_hold_even_when_cooldown_elapsed(state):
    c,h,p = fixture(); h["events"] = [event(1,ms=NOW-HOUR, state=state)]
    assert "no_unresolved_outcomes_in_declared_history" in review(c,h,p,now_ms=NOW)["failed_checks"]


def test_repeated_id_and_fingerprint_hold():
    c,h,p = fixture(); h["events"] = [event(1,ms=NOW-HOUR, digest=c["intent_sha256"])]
    c["client_order_id"] = "client-order-001"
    failed = review(c,h,p,now_ms=NOW)["failed_checks"]
    assert "candidate_id_not_reused" in failed
    assert "candidate_intent_not_repeated_24h" in failed


def test_side_flip_churn_detected():
    c,h,p = fixture(); h["events"] = [event(1,ms=NOW-180000,side="BUY"), event(2,ms=NOW-120000,side="SELL")]
    assert "side_flip_churn_within_cap" in review(c,h,p,now_ms=NOW)["failed_checks"]


@pytest.mark.parametrize("field", ["emergency_latched", "daily_loss_latched"])
def test_latched_breaker_blocks(field):
    c,h,p = fixture(); p[field] = True
    assert ("emergency_latch_clear" if field == "emergency_latched" else "daily_loss_latch_clear") in review(c,h,p,now_ms=NOW)["failed_checks"]


def test_history_coverage_and_freshness_fail_closed():
    c,h,p = fixture(); h["coverage_started_at_ms"] = NOW-DAY+1
    assert "complete_24h_coverage_declared" in review(c,h,p,now_ms=NOW)["failed_checks"]
    c,h,p = fixture(); h["snapshot_at_ms"] = NOW-3001
    assert "snapshot_current" in review(c,h,p,now_ms=NOW)["failed_checks"]
    h["snapshot_at_ms"] = NOW+1
    assert "snapshot_current" in review(c,h,p,now_ms=NOW)["failed_checks"]


def test_sequence_gap_duplicate_and_out_of_order_events_hold():
    c,h,p = fixture(); h["events"] = [event(1), event(3)]
    assert "contiguous_event_sequences" in review(c,h,p,now_ms=NOW)["failed_checks"]
    h["events"] = [event(1), event(2,ms=NOW-HOUR)]
    assert "chronological_events" in review(c,h,p,now_ms=NOW)["failed_checks"]
    h["events"] = [event(1),event(2)]; h["events"][1]["client_order_id"] = h["events"][0]["client_order_id"]
    assert "contiguous_event_sequences" in review(c,h,p,now_ms=NOW)["failed_checks"]


def test_wrong_account_holds_and_invalid_schema_rejected():
    c,h,p = fixture(); h["account_id"] = "another-account-001"
    assert "account_matches" in review(c,h,p,now_ms=NOW)["failed_checks"]
    c,h,p = fixture(); h["events"] = [event(1)]; h["events"][0]["api_key"] = "not-allowed"
    with pytest.raises(ValueError): review(c,h,p,now_ms=NOW)


@pytest.mark.parametrize("mutator", [
    lambda c,h,p: c.update(intent_sha256="not-a-digest"),
    lambda c,h,p: p.update(max_attempts_per_hour=True),
    lambda c,h,p: p.update(emergency_latched=1),
    lambda c,h,p: h.update(first_sequence=0),
    lambda c,h,p: h.update(events=[event(1,ms=NOW+1)]),
    lambda c,h,p: h.update(events=[event(1,state="FILLED")]),
    lambda c,h,p: h.update(events=[event(1,ms=NOW-HOUR)]*5001),
])
def test_invalid_input_rejected_or_held(mutator):
    c,h,p = fixture(); mutator(c,h,p)
    try:
        out = review(c,h,p,now_ms=NOW)
    except ValueError:
        return
    assert out["status"] == "HOLD_RECONCILIATION"


def test_deterministic_and_does_not_mutate_inputs():
    c,h,p = fixture(); h["events"] = [event(1,ms=NOW-HOUR)]
    original = deepcopy((c,h,p))
    assert review(c,h,p,now_ms=NOW) == review(c,h,p,now_ms=NOW)
    assert (c,h,p) == original
    c["side"] = "SELL"
    assert review(c,h,p,now_ms=NOW)["review_sha256"] != review(*original,now_ms=NOW)["review_sha256"]
