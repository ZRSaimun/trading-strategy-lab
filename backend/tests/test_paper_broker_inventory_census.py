"""Synthetic, no-network broker inventory census regressions."""
from copy import deepcopy
import pytest
from app.paper_broker_inventory_census import inspect_declared_inventory

NOW = 1_800_000_000_000
SHA = "a" * 64


def sample():
    expected = {
        "broker": "T212-INVEST-DEMO", "account_alias": "demo-account",
        "max_snapshot_age_ms": 5000, "max_transport_lag_ms": 2000,
        "unresolved_orders": [{"client_order_id": "client1", "intent_sha": SHA,
                               "instrument": "ABC", "side": "BUY", "quantity": "2",
                               "attempted_at_ms": NOW - 5000}],
    }
    observed = {
        "broker": "T212-INVEST-DEMO", "account_alias": "demo-account",
        "snapshot_id": "snapshot1", "sequence": 2,
        "observed_at_ms": NOW - 500, "received_at_ms": NOW - 100,
        "pages": [{"snapshot_id": "snapshot1", "index": 0, "total_pages": 1,
                   "complete": True,
                   "orders": [{"client_order_id": "client1", "broker_order_id": "broker1",
                               "instrument": "ABC", "side": "BUY", "quantity": "2",
                               "status": "FILLED", "filled_quantity": "2",
                               "fills": [{"fill_id": "fill1", "quantity": "2",
                                          "filled_at_ms": NOW - 1000}]}]}],
    }
    return expected, observed


def evaluate(change_e=None, change_o=None):
    e, o = sample()
    if change_e:
        change_e(e)
    if change_o:
        change_o(o)
    return inspect_declared_inventory(e, o, NOW)


def test_complete_census_is_never_broker_authentication_or_order_permission():
    result = evaluate()
    assert result["status"] == "DECLARED_TERMINAL_CANDIDATE_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["unresolved_order_count"] == 1
    for flag in ("broker_authenticated", "snapshot_completeness_authenticated",
                 "terminal_receipts_authenticated", "may_clear_unknown",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


@pytest.mark.parametrize("change,reason", [
    (lambda o: o.update(broker="T212-STOCKSISA-DEMO"), "account_identity"),
    (lambda o: o.update(account_alias="other"), "account_identity"),
    (lambda o: o.update(observed_at_ms=NOW-6000), "snapshot_freshness"),
    (lambda o: o.update(received_at_ms=NOW+1), "snapshot_freshness"),
    (lambda o: o.update(received_at_ms=NOW-3000), "snapshot_transport_lag"),
    (lambda o: o["pages"][0].update(complete=False), "page_census_complete"),
    (lambda o: o["pages"][0].update(index=1), "page_census_complete"),
    (lambda o: o["pages"][0].update(total_pages=2), "page_census_complete"),
    (lambda o: o["pages"][0].update(snapshot_id="other"), "page_census_complete"),
    (lambda o: o["pages"][0]["orders"].clear(), "order_population_complete"),
    (lambda o: o["pages"][0]["orders"].append(deepcopy(o["pages"][0]["orders"][0])), "duplicate_order_identity"),
    (lambda o: o["pages"][0]["orders"][0].update(instrument="XYZ"), "order_intent_mismatch"),
    (lambda o: o["pages"][0]["orders"][0].update(quantity="3"), "order_intent_mismatch"),
    (lambda o: o["pages"][0]["orders"][0].update(status="PARTIAL", filled_quantity="1"), "fill_quantity_reconciliation"),
    (lambda o: o["pages"][0]["orders"][0].update(status="OPEN", filled_quantity="0", fills=[]), "unresolved_order_state"),
    (lambda o: o["pages"][0]["orders"][0].update(status="REJECTED"), "status_quantity_reconciliation"),
    (lambda o: o["pages"][0]["orders"][0].update(filled_quantity="1"), "fill_quantity_reconciliation"),
    (lambda o: o["pages"][0]["orders"][0]["fills"][0].update(filled_at_ms=NOW+1), "fill_timing"),
    (lambda o: o["pages"][0]["orders"][0]["fills"][0].update(filled_at_ms=NOW-6000), "fill_timing"),
    (lambda o: o["pages"][0]["orders"][0]["fills"][0].update(quantity="3"), "fill_quantity_reconciliation"),
])
def test_mismatches_fail_closed(change, reason):
    result = evaluate(change_o=change)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert reason in result["failed_checks"]
    assert result["may_clear_unknown"] is False


def test_multiple_pages_duplicate_fill_ids_and_extra_orders():
    e, o = sample()
    e["unresolved_orders"].append({"client_order_id": "client2", "intent_sha": "b" * 64,
                                    "instrument": "DEF", "side": "SELL", "quantity": "1",
                                    "attempted_at_ms": NOW - 4000})
    second = deepcopy(o["pages"][0]["orders"][0])
    second.update(client_order_id="client2", broker_order_id="broker2", instrument="DEF",
                  side="SELL", quantity="1", filled_quantity="1")
    second["fills"][0]["quantity"] = "1"
    o["pages"][0].update(total_pages=2)
    o["pages"].append({"snapshot_id": "snapshot1", "index": 1, "total_pages": 2,
                       "complete": True, "orders": [second]})
    assert "duplicate_fill_identity" in inspect_declared_inventory(e, o, NOW)["failed_checks"]
    second["fills"][0]["fill_id"] = "fill2"
    assert inspect_declared_inventory(e, o, NOW)["status"] == "DECLARED_TERMINAL_CANDIDATE_UNVERIFIED"
    second["client_order_id"] = "stranger"
    reasons = inspect_declared_inventory(e, o, NOW)["failed_checks"]
    assert "unexpected_account_order" in reasons and "order_population_complete" in reasons


def test_snapshot_before_attempt_holds():
    assert "snapshot_precedes_attempt" in evaluate(change_e=lambda e: e["unresolved_orders"][0].update(
        attempted_at_ms=NOW-100))["failed_checks"]


@pytest.mark.parametrize("change_e,change_o", [
    (lambda e: e.update(broker="T212-CFD"), None),
    (lambda e: e["unresolved_orders"][0].update(intent_sha="0"*64), None),
    (lambda e: e["unresolved_orders"][0].update(quantity="NaN"), None),
    (lambda e: e["unresolved_orders"][0].update(quantity=2.0), None),
    (lambda e: e["unresolved_orders"][0].update(attempted_at_ms=True), None),
    (lambda e: e.update(max_snapshot_age_ms=60001), None),
    (lambda e: e.update(unresolved_orders=[]), None),
    (None, lambda o: o["pages"][0]["orders"][0].update(status="UNKNOWN")),
    (None, lambda o: o["pages"][0]["orders"][0]["fills"][0].update(quantity="Infinity")),
    (None, lambda o: o["pages"][0]["orders"][0]["fills"][0].update(quantity="0")),
    (None, lambda o: o["pages"][0]["orders"][0].update(extra="unexpected")),
    (None, lambda o: o.update(pages=[])),
    (None, lambda o: o.update(sequence=True)),
])
def test_invalid_schema_rejected(change_e, change_o):
    with pytest.raises(ValueError):
        evaluate(change_e, change_o)


def test_bound_page_population():
    with pytest.raises(ValueError):
        evaluate(change_o=lambda o: o.update(pages=[deepcopy(o["pages"][0]) for _ in range(17)]))


def test_never_mutates_caller_data():
    e, o = sample()
    before = deepcopy((e, o))
    inspect_declared_inventory(e, o, NOW)
    assert (e, o) == before
