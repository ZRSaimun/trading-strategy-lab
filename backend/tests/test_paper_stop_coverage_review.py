"""Synthetic stop-coverage checks; no broker calls or order execution."""
from dataclasses import replace
import pytest
from app.paper_stop_coverage_review import (
    PaperOpenPosition, PaperStopAcknowledgement, CoveragePolicy, review_paper_stop_coverage,
)

NOW = 1_790_000_000_000
POSITION = PaperOpenPosition("account-0001", "position-0001", "XAUUSD", "DEMO", "OTC",
                             "LONG", "2", "100", "10", "100", 4, NOW - 300)
STOP = PaperStopAcknowledgement("stop-order-001", "account-0001", "position-0001",
                                "XAUUSD", "DEMO", "OTC", "SELL", True, "ACTIVE",
                                "2", "0", "98", 4, NOW - 200, NOW - 1000)
POLICY = CoveragePolicy(max_snapshot_age_ms=1000, assumed_exit_cost_cash="1",
                        adverse_stress_price="97")


def run(position=POSITION, stops=(STOP,), policy=POLICY, now=NOW):
    return review_paper_stop_coverage(position, stops, policy, server_now_ms=now)


def test_exact_match_is_still_non_executing_and_unauthenticated():
    r = run()
    assert r["structural_coverage_match"] and r["failed_checks"] == []
    assert r["declared_stressed_loss_cash"] == "61"
    assert r["decision"] == "HOLD_RECONCILIATION"
    assert r["requires_human_reconciliation"]
    assert not r["may_execute_real_order"] and not r["may_execute_paper_order"]
    assert not r["may_release_risk_reservation"] and not r["broker_state_authenticated"]
    assert not r["stop_execution_guaranteed"]


@pytest.mark.parametrize("change,check", [
    ({"account_id": "account-0002"}, "identity_matches"),
    ({"position_id": "position-0002"}, "identity_matches"),
    ({"instrument": "US100"}, "identity_matches"),
    ({"provider": "OTHER"}, "identity_matches"),
    ({"venue": "OTHER"}, "identity_matches"),
    ({"side": "BUY"}, "close_side"),
    ({"reduce_only": False}, "reduce_only"),
    ({"reduce_only": 1}, "reduce_only"),
    ({"status": "PENDING"}, "active"),
    ({"status": "UNKNOWN"}, "active"),
    ({"status": "CANCELLED"}, "active"),
    ({"position_revision": 3}, "revision_matches"),
    ({"remaining_quantity": "1.999999999999999999"}, "exact_remaining_coverage"),
    ({"remaining_quantity": "3"}, "exact_remaining_coverage"),
    ({"already_executed_quantity": "0.1"}, "no_partial_execution"),
    ({"observed_at_ms": NOW - 2000}, "fresh_observation"),
    ({"acknowledged_at_ms": NOW + 1}, "acknowledgement_order"),
])
def test_stop_discrepancies_hold(change, check):
    r = run(stops=(replace(STOP, **change),))
    assert not r["structural_coverage_match"]
    assert any(check in item for item in r["failed_checks"])
    assert not r["may_release_risk_reservation"]


def test_no_stop_is_never_covered():
    r = run(stops=())
    assert not r["structural_coverage_match"]
    assert "exactly_one_stop" in r["failed_checks"]


def test_duplicate_and_multiple_stops_fail_closed():
    for stops in ((STOP, STOP), (STOP, replace(STOP, order_id="stop-order-002"))):
        r = run(stops=stops)
        assert not r["structural_coverage_match"]


def test_stale_position_and_future_clock_hold():
    assert "position_snapshot_fresh" in run(position=replace(POSITION, observed_at_ms=NOW - 2000))["failed_checks"]
    assert "position_snapshot_fresh" in run(position=replace(POSITION, observed_at_ms=NOW + 1))["failed_checks"]


def test_stressed_loss_uses_worse_of_stop_and_declared_gap():
    assert run(policy=replace(POLICY, adverse_stress_price="99"))["declared_stressed_loss_cash"] == "41"
    assert run(policy=replace(POLICY, adverse_stress_price="95"))["declared_stressed_loss_cash"] == "101"
    assert "declared_stressed_loss_within_cap" in run(policy=replace(POLICY, adverse_stress_price="95"))["failed_checks"]


def test_short_position_uses_adverse_higher_exit():
    pos = replace(POSITION, side="SHORT")
    stop = replace(STOP, side="BUY", stop_price="102")
    p = replace(POLICY, adverse_stress_price="103")
    assert run(position=pos, stops=(stop,), policy=p)["declared_stressed_loss_cash"] == "61"
    assert run(position=pos, stops=(stop,), policy=p)["structural_coverage_match"]


def test_missing_stress_is_not_optimistically_treated_as_safe():
    r = run(policy=replace(POLICY, adverse_stress_price="0"))
    assert "stress_supplied" in r["failed_checks"]
    assert not r["structural_coverage_match"]


@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-1", "1e100", "01", " 1", "0.0000000000000000001", 1.0, True])
def test_invalid_quantities_rejected(bad):
    with pytest.raises(ValueError):
        run(position=replace(POSITION, quantity=bad))


@pytest.mark.parametrize("bad", [True, 0, -1, 3001, "1000"])
def test_invalid_age_policy_rejected(bad):
    with pytest.raises(ValueError):
        run(policy=replace(POLICY, max_snapshot_age_ms=bad))


def test_unbounded_stop_list_rejected():
    with pytest.raises(ValueError):
        run(stops=(STOP,) * 9)
    with pytest.raises(ValueError):
        run(stops=[STOP])


def test_fingerprint_deterministic_and_input_immutable():
    assert run() == run()
    assert run(stops=(replace(STOP, stop_price="97"),))["review_fingerprint_sha256"] != run()["review_fingerprint_sha256"]
    assert POSITION.quantity == "2" and STOP.stop_price == "98"
