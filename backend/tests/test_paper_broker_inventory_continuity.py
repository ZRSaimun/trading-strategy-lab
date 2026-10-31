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
    (lambda e,p,c: p.update(observed_at_ms=c["observed_at_ms"] - e["max_snapshot_age_ms"] - 1,
                             received_at_ms=c["observed_at_ms"] - e["max_snapshot_age_ms"] + 99),
     "snapshot_observation_gap_exceeds_freshness_window"),
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



def test_observation_gap_at_freshness_window_boundary_is_not_held():
    e, p, c = sample()
    p["observed_at_ms"] = c["observed_at_ms"] - e["max_snapshot_age_ms"]
    p["received_at_ms"] = p["observed_at_ms"] + 100
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED"
    assert "snapshot_observation_gap_exceeds_freshness_window" not in result["failed_checks"]
    assert result["may_clear_unknown"] is False



def test_previous_checkpoint_transport_lag_over_limit_holds():
    e, p, c = sample()
    p["observed_at_ms"] = NOW - 3000
    p["received_at_ms"] = NOW - 750  # 2250 ms > declared 2000 ms
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert "previous_snapshot_transport_lag" in result["failed_checks"]
    assert "snapshot_delivery_overlap" not in result["failed_checks"]
    assert "snapshot_observation_gap_exceeds_freshness_window" not in result["failed_checks"]
    assert result["may_clear_unknown"] is False
    assert result["may_submit_real_order"] is False


def test_previous_checkpoint_transport_lag_at_limit_remains_unverified():
    e, p, c = sample()
    p["observed_at_ms"] = NOW - 2750
    p["received_at_ms"] = NOW - 750  # exactly declared 2000 ms
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED"
    assert "previous_snapshot_transport_lag" not in result["failed_checks"]
    assert result["may_clear_unknown"] is False
    assert result["may_submit_paper_order"] is False

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


@pytest.mark.parametrize("field", ["client_order_id", "broker_order_id"])
def test_prior_duplicate_order_identity_holds(field):
    e, p, c = sample()
    repeated = deepcopy(p["pages"][0]["orders"][0])
    if field == "client_order_id":
        repeated["broker_order_id"] = "another-broker-order"
    else:
        repeated["client_order_id"] = "another-client-order"
    p["pages"][0]["orders"].append(repeated)
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert "previous_duplicate_order_identity" in result["failed_checks"]
    assert result["may_clear_unknown"] is False
    assert result["may_submit_real_order"] is False


def test_prior_duplicate_identity_across_pages_holds():
    e, p, c = sample()
    p["pages"][0]["total_pages"] = 2
    p["pages"].append({"snapshot_id": "prior", "index": 1,
                       "total_pages": 2, "complete": True,
                       "orders": deepcopy(p["pages"][0]["orders"])})
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_duplicate_order_identity" in result["failed_checks"]
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"


@pytest.mark.parametrize("edit", [
    lambda order: order.update(broker_order_id="invalid id with spaces"),
    lambda order: order.update(client_order_id=True),
    lambda order: order.update(unexpected="field"),
])
def test_prior_order_identity_schema_invalid_fails_closed(edit):
    e, p, c = sample()
    edit(p["pages"][0]["orders"][0])
    with pytest.raises(ValueError):
        inspect_declared_inventory_continuity(e, p, c, NOW)


def test_prior_disappeared_order_holds():
    e, p, c = sample()
    another = deepcopy(p["pages"][0]["orders"][0])
    another["client_order_id"] = "order2"
    another["broker_order_id"] = "broker2"
    another["fills"][0]["fill_id"] = "fill2"
    p["pages"][0]["orders"].append(another)
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert "previous_order_disappeared" in result["failed_checks"]
    assert result["prior_checkpoint_authenticated"] is False
    assert result["may_clear_unknown"] is False


def test_previous_duplicate_fill_within_order_holds():
    e, p, c = sample()
    order = p["pages"][0]["orders"][0]
    order["quantity"] = "2"
    order["filled_quantity"] = "2"
    order["fills"].append(deepcopy(order["fills"][0]))
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_duplicate_fill_identity" in result["failed_checks"]
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert result["may_clear_unknown"] is False


def test_previous_duplicate_fill_across_pages_holds():
    e, p, c = sample()
    other = deepcopy(p["pages"][0]["orders"][0])
    other["client_order_id"] = "order2"
    other["broker_order_id"] = "broker2"
    p["pages"][0]["total_pages"] = 2
    p["pages"].append({"snapshot_id": "prior", "index": 1, "total_pages": 2,
                       "complete": True, "orders": [other]})
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_duplicate_fill_identity" in result["failed_checks"]
    assert "previous_duplicate_order_identity" not in result["failed_checks"]
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("edit", [
    lambda f: f.update(fill_id=True),
    lambda f: f.update(quantity="0"),
    lambda f: f.update(quantity="NaN"),
    lambda f: f.update(filled_at_ms=True),
    lambda f: f.update(unexpected="field"),
])
def test_previous_fill_schema_fails_closed(edit):
    e, p, c = sample()
    edit(p["pages"][0]["orders"][0]["fills"][0])
    with pytest.raises(ValueError):
        inspect_declared_inventory_continuity(e, p, c, NOW)


def test_previous_fill_after_snapshot_observation_holds():
    e, p, c = sample()
    p["pages"][0]["orders"][0]["fills"][0]["filled_at_ms"] = p["observed_at_ms"] + 1
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_fill_after_observation" in result["failed_checks"]
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"


def test_previous_fill_sum_mismatch_holds():
    e, p, c = sample()
    p["pages"][0]["orders"][0]["fills"][0]["quantity"] = "0.5"
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_fill_quantity_reconciliation" in result["failed_checks"]
    assert result["may_clear_unknown"] is False


def test_previous_order_status_mismatch_holds():
    e, p, c = sample()
    p["pages"][0]["orders"][0]["status"] = "OPEN"
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_status_quantity_reconciliation" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_previous_partial_fill_is_consistent_but_unverified():
    e, p, c = sample()
    prior = p["pages"][0]["orders"][0]
    prior.update(status="PARTIAL", filled_quantity="0.5")
    prior["fills"][0]["quantity"] = "0.5"
    current = c["pages"][0]["orders"][0]
    current["fills"][0]["quantity"] = "0.5"
    current["fills"].append({"fill_id": "fill2", "quantity": "0.5",
                             "filled_at_ms": NOW - 1000})
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["may_clear_unknown"] is False


def test_previous_fill_population_over_bound_raises():
    e, p, c = sample()
    p["pages"][0]["orders"][0]["fills"] *= 2049
    with pytest.raises(ValueError, match="Invalid previous fill population"):
        inspect_declared_inventory_continuity(e, p, c, NOW)


@pytest.mark.parametrize("edit", [
    lambda o: o.update(status="UNKNOWN"),
    lambda o: o.update(side=True),
    lambda o: o.update(quantity="0"),
    lambda o: o.update(filled_quantity="-1"),
    lambda o: o.update(fills="not-a-list"),
])
def test_previous_order_economics_invalid_schema_raises(edit):
    e, p, c = sample()
    edit(p["pages"][0]["orders"][0])
    with pytest.raises(ValueError):
        inspect_declared_inventory_continuity(e, p, c, NOW)


@pytest.mark.parametrize("edit,reason", [
    (lambda e,p,c: p["pages"][0]["orders"][0].update(broker_order_id="broker-old"),
     "broker_order_identity_changed"),
    (lambda e,p,c: p["pages"][0]["orders"][0].update(instrument="XAGUSD"),
     "order_contract_changed"),
    (lambda e,p,c: p["pages"][0]["orders"][0].update(side="SELL"),
     "order_contract_changed"),
    (lambda e,p,c: p["pages"][0]["orders"][0].update(quantity="2", status="PARTIAL"),
     "order_contract_changed"),
    (lambda e,p,c: c["pages"][0]["orders"][0].update(
        status="CANCELLED", filled_quantity="0", fills=[]),
     "cumulative_fill_regressed"),
    (lambda e,p,c: c["pages"][0]["orders"][0].update(
        status="CANCELLED", filled_quantity="0", fills=[]),
     "terminal_order_state_changed"),
    (lambda e,p,c: p["pages"][0]["orders"][0]["fills"][0].update(
        filled_at_ms=NOW - 11000),
     "previous_fill_before_order_attempt"),
])
def test_cross_snapshot_order_regression_holds(edit, reason):
    result = inspect(edit)
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert reason in result["failed_checks"]
    assert result["may_clear_unknown"] is False
    assert result["may_submit_real_order"] is False


def test_prior_fill_receipt_mutation_holds():
    e, p, c = sample()
    prior = p["pages"][0]["orders"][0]
    prior.update(status="PARTIAL", filled_quantity="0.5")
    prior["fills"][0]["quantity"] = "0.5"
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "previous_fill_missing_or_changed" in result["failed_checks"]
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"


def test_backdated_new_fill_after_prior_open_snapshot_holds():
    e, p, c = sample()
    prior = p["pages"][0]["orders"][0]
    prior.update(status="OPEN", filled_quantity="0", fills=[])
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "new_fill_backdated_before_prior_observation" in result["failed_checks"]
    assert result["may_clear_unknown"] is False


def test_missing_prior_order_attempted_before_checkpoint_holds():
    e, p, c = sample()
    p["pages"][0]["orders"] = []
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "order_missing_from_prior_snapshot" in result["failed_checks"]
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"


def test_order_first_attempted_after_prior_checkpoint_remains_unverified():
    e, p, c = sample()
    p["pages"][0]["orders"] = []
    e["unresolved_orders"][0]["attempted_at_ms"] = NOW - 1000
    c["pages"][0]["orders"][0]["fills"][0]["filled_at_ms"] = NOW - 800
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED"
    assert result["may_clear_unknown"] is False
    assert result["may_submit_real_order"] is False


def test_prior_partial_state_cannot_revert_to_open():
    e, p, c = sample()
    p["pages"][0]["orders"][0].update(
        status="PARTIAL", quantity="2")
    c["pages"][0]["orders"][0].update(
        status="OPEN", filled_quantity="0", fills=[])
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert "partial_order_state_regressed" in result["failed_checks"]
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"


def test_prior_terminal_order_before_attempt_holds_without_fills():
    e, p, c = sample()
    # A prior REJECTED row has no fill to trigger the existing fill-time check.
    # Its presence before the declared attempt is still impossible.
    e["unresolved_orders"][0]["attempted_at_ms"] = NOW - 1000
    for snap in (p, c):
        snap["pages"][0]["orders"][0].update(
            status="REJECTED", filled_quantity="0", fills=[])
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert "prior_order_precedes_attempt" in result["failed_checks"]
    assert result["current_inventory_failed_checks"] == []
    assert result["may_clear_unknown"] is False
    assert result["may_submit_real_order"] is False


def test_prior_order_at_exact_attempt_boundary_remains_unverified():
    e, p, c = sample()
    e["unresolved_orders"][0]["attempted_at_ms"] = p["observed_at_ms"]
    for snap in (p, c):
        snap["pages"][0]["orders"][0].update(
            status="REJECTED", filled_quantity="0", fills=[])
    original = deepcopy((e, p, c))
    result = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert result["status"] == "DECLARED_INVENTORY_CONTINUITY_UNVERIFIED"
    assert "prior_order_precedes_attempt" not in result["failed_checks"]
    assert (e, p, c) == original
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False


def test_declared_evidence_digest_is_stable_and_non_authorizing():
    e, p, c = sample()
    original = deepcopy((e, p, c))
    first = inspect_declared_inventory_continuity(e, p, c, NOW)
    second = inspect_declared_inventory_continuity(e, p, c, NOW)
    digest = first["declared_evidence_sha256"]
    assert len(digest) == 64
    assert all(char in "0123456789abcdef" for char in digest)
    assert digest == second["declared_evidence_sha256"]
    assert (e, p, c) == original
    assert first["broker_authenticated"] is False
    assert first["may_clear_unknown"] is False
    assert first["may_submit_real_order"] is False


def test_declared_evidence_digest_changes_with_evidence_not_only_reasons():
    e, p, c = sample()
    baseline = inspect_declared_inventory_continuity(e, p, c, NOW)
    c["received_at_ms"] -= 1  # Still a clean declared transition.
    changed = inspect_declared_inventory_continuity(e, p, c, NOW)
    assert baseline["failed_checks"] == changed["failed_checks"] == []
    assert baseline["declared_evidence_sha256"] != changed["declared_evidence_sha256"]
    assert changed["may_submit_paper_order"] is False


def test_declared_evidence_digest_canonicalizes_mapping_key_order():
    e, p, c = sample()
    baseline = inspect_declared_inventory_continuity(e, p, c, NOW)
    reversed_e = dict(reversed(list(e.items())))
    reversed_p = dict(reversed(list(p.items())))
    reversed_c = dict(reversed(list(c.items())))
    reordered = inspect_declared_inventory_continuity(reversed_e, reversed_p, reversed_c, NOW)
    assert baseline["declared_evidence_sha256"] == reordered["declared_evidence_sha256"]


def test_invalid_page_completeness_type_fails_closed_before_fingerprinting():
    e, p, c = sample()
    p["pages"][0]["complete"] = {"untrusted": ["not a boolean"]}
    with pytest.raises(ValueError, match="Invalid declared page completeness type"):
        inspect_declared_inventory_continuity(e, p, c, NOW)


def test_missing_previous_digest_remains_a_hold():
    result = inspect(prior=False)
    assert len(result["declared_evidence_sha256"]) == 64
    assert result["status"] == "HOLD_INVENTORY_CONTINUITY"
    assert result["may_clear_unknown"] is False
