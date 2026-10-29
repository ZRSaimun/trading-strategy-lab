"""Offline regression tests; no broker connection or order execution."""
from copy import deepcopy

import pytest

from app.paper_broker_inventory_continuity import inspect_declared_inventory_continuity

NOW = 1_800_000_000_000


def sample():
    expected = {
        "broker": "PAPER-LOCAL", "account_alias": "demo",
        "max_snapshot_age_ms": 5000, "max_transport_lag_ms": 2000,
        "unresolved_orders": [{"client_order_id": "order1", "intent_sha": "a" * 64,
                               "instrument": "XAUUSD", "side": "BUY", "quantity": "1",
                               "attempted_at_ms": NOW - 10_000}],
    }
    def snapshot(sid, seq, obs, rec):
        return {
            "broker": "PAPER-LOCAL", "account_alias": "demo", "snapshot_id": sid,
            "sequence": seq, "observed_at_ms": obs, "received_at_ms": rec,
            "pages": [{"snapshot_id": sid, "index": 0, "total_pages": 1,
                       "complete": True, "orders": [{
                           "client_order_id": "order1", "broker_order_id": "broker1",
                           "instrument": "XAUUSD", "side": "BUY", "quantity": "1",
                           "status": "FILLED", "filled_quantity": "1",
                           "fills": [{"fill_id": "fill1", "quantity": "1",
                                      "filled_at_ms": NOW - 9000}]}]}],
        }
    return expected, snapshot("prior", 3, NOW - 2000, NOW - 1500), snapshot(
        "current", 4, NOW - 500, NOW - 100)


def inspect(change=None, *, prior=True):
    expected, previous, current = sample()
    if change:
        change(expected, previous, current)
    return inspect_declared_inventory_continuity(expected, previous if prior else None,
                                                  current, NOW)


def test_clean_transition_remains_nonexecuting_and_unverified():
    result = inspect()
    assert result["status"] == "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["current_inventory_status"] == "DECLARED_TERMINAL_CANDIDATE_UNVERIFIED"
    for flag in ("prior_checkpoint_authenticated", "broker_authenticated",
                 "inventory_continuity_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


def test_missing_previous_holds():
    assert "missing_prior_inventory_checkpoint" in inspect(prior=False)["failed_checks"]


@pytest.mark.parametrize("edit,reason", [
    (lambda e,p,c: c.update(snapshot_id=p["snapshot_id"]), "snapshot_id_reused"),
    (lambda e,p,c: c.update(sequence=p["sequence"]), "snapshot_sequence_not_advanced"),
    (lambda e,p,c: c.update(sequence=p["sequence"] - 1), "snapshot_sequence_not_advanced"),
    (lambda e,p,c: c.update(sequence=p["sequence"] + 2), "snapshot_sequence_gap"),
    (lambda e,p,c: c.update(observed_at_ms=p["observed_at_ms"]), "snapshot_observation_not_advanced"),
    (lambda e,p,c: c.update(received_at_ms=p["received_at_ms"]), "snapshot_receipt_not_advanced"),
    (lambda e,p,c: c.update(observed_at_ms=p["received_at_ms"]), "snapshot_delivery_overlap"),
    (lambda e,p,c: p.update(broker="T212-INVEST-DEMO"), "previous_account_identity"),
    (lambda e,p,c: p.update(account_alias="another"), "previous_account_identity"),
    (lambda e,p,c: p.update(received_at_ms=NOW + 1), "previous_snapshot_clock_invalid"),
    (lambda e,p,c: p["pages"][0].update(complete=False), "previous_page_census_incomplete"),
    (lambda e,p,c: c.update(observed_at_ms=NOW - 6000), "current_inventory:snapshot_freshness"),
])
def test_transition_fail_closed(edit, reason):
    result = inspect(edit)
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert reason in result["failed_checks"]
    assert result["may_clear_unknown"] is False
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("edit", [
    lambda e,p,c: p.update(sequence=True),
    lambda e,p,c: p.update(pages=[]),
    lambda e,p,c: p["pages"][0].update(index=True),
    lambda e,p,c: p["pages"][0].update(extra="bad"),
    lambda e,p,c: p.update(extra="bad"),
    lambda e,p,c: c.update(sequence=True),
])
def test_invalid_schemas_raise(edit):
    with pytest.raises(ValueError):
        inspect(edit)


def test_non_mutating_and_deterministic():
    e, p, c = sample()
    original = deepcopy((e, p, c))
    first = inspect_declared_inventory_continuity(e, p, c, NOW)
    second = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert first == second
    assert (e, p, c) == original


def test_prior_snapshot_not_claimed_to_be_authenticated():
    e, p, c = sample()
    p["pages"][0]["orders"] = []  # Caller-declared prior contents are not proof.
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["prior_checkpoint_authenticated"] is False
    assert result["may_clear_unknown"] is False


def test_prior_aggregate_population_bound():
    e, p, c = sample()
    p["pages"][0]["total_pages"] = 2
    p["pages"][0]["orders"] *= 256
    p["pages"].append({"snapshot_id": "prior", "index": 1,
                       "total_pages": 2, "complete": True,
                       "orders": deepcopy(p["pages"][0]["orders"][:1])})
    with pytest.raises(ValueError, match="Previous order population exceeds bound"):
        inspect_declared_inventory_continuity(e, p, c, NOW)
