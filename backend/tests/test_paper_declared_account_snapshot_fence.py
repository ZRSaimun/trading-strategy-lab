"""Synthetic account freshness tests; no broker calls or order submissions."""
from copy import deepcopy
import pytest

from app.paper_declared_account_snapshot_fence import inspect_declared_account_snapshot_fence

NOW = 1_800_000_000_000


def fixture():
    account = dict(broker="PAPER-LOCAL", account_alias="demo1", equity="10000",
                   free_margin="5000", daily_realized_pnl="-100", open_notional="1000",
                   open_risk="50", circuit_breaker_open=False)
    quote = dict(instrument="XAUUSD", source="feedA", bid="99.9", ask="100",
                 observed_at_ms=NOW-150, received_at_ms=NOW-100)
    current = dict(account=deepcopy(account), risk_quote=deepcopy(quote),
                   revision=12, session_epoch=2, positions_revision=5, orders_revision=8,
                   observed_at_ms=NOW-180, received_at_ms=NOW-120,
                   positions_synced_at_ms=NOW-200, orders_synced_at_ms=NOW-220,
                   reconciliation_complete=True, unresolved_attempts=0)
    previous = deepcopy(current)
    previous.update(revision=11, positions_revision=4, orders_revision=7,
                    observed_at_ms=NOW-700, received_at_ms=NOW-600)
    policy = dict(max_account_age_ms=1000, max_account_transport_lag_ms=500,
                  max_quote_account_skew_ms=300, max_positions_sync_age_ms=1000,
                  max_orders_sync_age_ms=1000)
    return [account, quote, current, previous, policy, NOW]


def inspect(args):
    return inspect_declared_account_snapshot_fence(*args)


def test_clean_declared_evidence_does_not_authorize():
    result = inspect(fixture())
    assert result["status"] == "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED"
    assert result["failed_checks"] == []
    for key in ("broker_authenticated", "account_authenticated", "quote_authenticated",
                "external_reconciliation_verified", "atomic_reservation_verified",
                "stop_guaranteed", "may_submit_paper_order", "may_submit_real_order"):
        assert result[key] is False
    assert result["requires_individual_owner_approval"] is True


@pytest.mark.parametrize("position,path,value,check", [
    (2, "observed_at_ms", NOW-2000, "stale_or_future_account_snapshot"),
    (2, "received_at_ms", NOW+1, "stale_or_future_account_snapshot"),
    (2, "observed_at_ms", NOW-800, "account_transport_lag"),
    (2, "positions_synced_at_ms", NOW-2000, "stale_or_future_positions_sync"),
    (2, "orders_synced_at_ms", NOW+1, "stale_or_future_orders_sync"),
    (2, "reconciliation_complete", False, "account_reconciliation_incomplete"),
    (2, "unresolved_attempts", 1, "unresolved_order_attempts"),
    (2, "revision", 11, "account_revision_replay"),
    (2, "positions_revision", 3, "positions_revision_rollback"),
    (2, "orders_revision", 6, "orders_revision_rollback"),
    (2, "session_epoch", 1, "session_epoch_rollback"),
    (2, "session_epoch", 3, "session_change_requires_external_reconciliation"),
    (2, "observed_at_ms", NOW-700, "snapshot_time_replay"),
    (1, "observed_at_ms", NOW-1000, "quote_account_time_skew"),
])
def test_unsafe_declared_evidence_holds(position, path, value, check):
    args = fixture()
    args[position][path] = value
    assert check in inspect(args)["failed_checks"]


def test_risk_account_mismatch():
    args = fixture()
    args[0]["equity"] = "9000"
    assert "risk_account_snapshot_mismatch" in inspect(args)["failed_checks"]


def test_quote_mismatch_even_if_numeric_price_equal():
    args = fixture()
    args[1]["ask"] = "100.00"
    assert "risk_quote_snapshot_mismatch" in inspect(args)["failed_checks"]


def test_account_identity_changed():
    args = fixture()
    args[3]["account"]["account_alias"] = "other"
    assert "account_identity_changed" in inspect(args)["failed_checks"]


def test_missing_prior_does_not_claim_monotonic_proof():
    args = fixture()
    args[3] = None
    result = inspect(args)
    assert result["status"] == "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED"
    assert result["external_reconciliation_verified"] is False


def test_no_mutation():
    args = fixture()
    before = deepcopy(args)
    inspect(args)
    assert args == before


@pytest.mark.parametrize("position,key,value", [
    (2, "revision", True), (2, "unresolved_attempts", -1),
    (2, "reconciliation_complete", 1), (2, "session_epoch", 0),
    (2, "account", None), (2, "unknown", "unexpected"),
    (4, "max_account_age_ms", 3001),
    (4, "max_account_transport_lag_ms", 1001),
    (4, "max_quote_account_skew_ms", 1001),
    (4, "max_positions_sync_age_ms", 3001),
    (4, "max_orders_sync_age_ms", 3001),
    (4, "max_orders_sync_age_ms", True),
])
def test_malformed_or_unsafe_policy_raises(position, key, value):
    args = fixture()
    args[position][key] = value
    with pytest.raises(ValueError):
        inspect(args)


def test_bool_int_type_confusion_detected():
    args = fixture()
    args[0]["circuit_breaker_open"] = 0
    with pytest.raises(ValueError):
        inspect(args)


def test_circuit_breaker_holds():
    args = fixture()
    args[0]["circuit_breaker_open"] = True
    args[2]["account"]["circuit_breaker_open"] = True
    assert "account_circuit_breaker_open" in inspect(args)["failed_checks"]


@pytest.mark.parametrize("position,key,value", [
    (0, "equity", "NaN"), (0, "equity", "0"),
    (0, "free_margin", -1), (0, "broker", "UNSUPPORTED-CFD"),
    (1, "bid", "0"), (1, "ask", "99"),
    (1, "source", ""), (1, "observed_at_ms", True),
])
def test_malformed_account_quote_rejected(position, key, value):
    args = fixture()
    args[position][key] = value
    with pytest.raises(ValueError):
        inspect(args)


def test_quote_observed_after_received_holds():
    args = fixture()
    args[1]["observed_at_ms"] = NOW-50
    assert "invalid_quote_chronology" in inspect(args)["failed_checks"]


@pytest.mark.parametrize("field,rollback,check", [
    ("positions_synced_at_ms", NOW-201, "positions_sync_time_rollback"),
    ("orders_synced_at_ms", NOW-221, "orders_sync_time_rollback"),
])
def test_fresh_inventory_sync_timestamp_rollback_holds(field, rollback, check):
    args = fixture()
    args[2][field] = rollback
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert check in result["failed_checks"]
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("field,new_prior,check", [
    ("observed_at_ms", NOW-140, "quote_observation_time_rollback"),
    ("received_at_ms", NOW-90, "quote_receipt_time_rollback"),
])
def test_fresh_primary_quote_timestamp_rollback_holds(field, new_prior, check):
    args = fixture()
    args[3]["risk_quote"][field] = new_prior
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert check in result["failed_checks"]
    assert result["may_submit_paper_order"] is False


def test_repeated_inventory_sync_and_quote_timestamps_do_not_alone_hold():
    # Identical fresh inventory/quote timestamps can represent no change;
    # this is still only a caller-declared diagnostic, never authorization.
    result = inspect(fixture())
    assert result["failed_checks"] == []
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("field,value", [
    ("bid", "99.8"),
    ("ask", "100.1"),
])
def test_same_observation_with_changed_price_holds(field, value):
    args = fixture()
    args[1][field] = value
    args[2]["risk_quote"][field] = value
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert "quote_payload_changed_without_new_observation" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("advance_quote_time", [False, True])
def test_same_instrument_primary_source_switch_holds(advance_quote_time):
    args = fixture()
    args[1]["source"] = "feedB"
    args[2]["risk_quote"]["source"] = "feedB"
    if advance_quote_time:
        args[1]["observed_at_ms"] = NOW-140
        args[1]["received_at_ms"] = NOW-90
        args[2]["risk_quote"].update(
            observed_at_ms=NOW-140, received_at_ms=NOW-90,
        )
    result = inspect(args)
    assert "quote_source_change_requires_external_evidence" in result["failed_checks"]
    assert result["may_submit_paper_order"] is False


def test_changed_price_with_new_observation_is_not_payload_replay():
    args = fixture()
    args[1].update(ask="100.1", observed_at_ms=NOW-140, received_at_ms=NOW-90)
    args[2]["risk_quote"].update(args[1])
    result = inspect(args)
    assert "quote_payload_changed_without_new_observation" not in result["failed_checks"]
    assert "quote_source_change_requires_external_evidence" not in result["failed_checks"]
    assert result["status"] == "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_quote_payload_and_source_checks_do_not_mutate_inputs():
    args = fixture()
    args[1].update(source="feedB", bid="99.8")
    args[2]["risk_quote"].update(args[1])
    before = deepcopy(args)
    assert inspect(args)["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert args == before


@pytest.mark.parametrize("mutate,expected", [
    ("breaker_reset", "circuit_breaker_reset_requires_external_evidence"),
    ("unresolved_reduction", "unknown_attempt_reduction_requires_external_evidence"),
    ("reconciliation_release", "reconciliation_release_requires_external_evidence"),
    ("position_notional_without_revision", "positions_changed_without_revision"),
    ("position_risk_without_revision", "positions_changed_without_revision"),
    ("attempt_count_without_revision", "unknown_attempts_changed_without_orders_revision"),
])
def test_standalone_snapshot_rejects_unverified_safety_release(mutate, expected):
    args = fixture()
    prior = args[3]
    current = args[2]
    if mutate == "breaker_reset":
        prior["account"]["circuit_breaker_open"] = True
    elif mutate == "unresolved_reduction":
        prior["unresolved_attempts"] = 2
    elif mutate == "reconciliation_release":
        prior["reconciliation_complete"] = False
    elif mutate == "position_notional_without_revision":
        prior["positions_revision"] = current["positions_revision"]
        prior["account"]["open_notional"] = "900"
    elif mutate == "position_risk_without_revision":
        prior["positions_revision"] = current["positions_revision"]
        prior["account"]["open_risk"] = "40"
    elif mutate == "attempt_count_without_revision":
        prior["orders_revision"] = current["orders_revision"]
        prior["unresolved_attempts"] = 1
    before = deepcopy(args)
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert expected in result["failed_checks"]
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False
    assert args == before


def test_standalone_snapshot_accepts_declared_monotonic_safety_state():
    args = fixture()
    args[3]["unresolved_attempts"] = 0
    args[3]["reconciliation_complete"] = True
    args[3]["account"]["circuit_breaker_open"] = False
    result = inspect(args)
    assert result["status"] == "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["broker_authenticated"] is False
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("kind", ["notional", "risk", "orders"])
def test_changed_inventory_requires_advanced_sync(kind):
    args = fixture()
    if kind == "notional":
        args[0]["open_notional"] = "1200"
        args[2]["account"]["open_notional"] = "1200"
        expected = "positions_changed_without_new_sync"
    elif kind == "risk":
        args[0]["open_risk"] = "60"
        args[2]["account"]["open_risk"] = "60"
        expected = "positions_changed_without_new_sync"
    else:
        args[2]["unresolved_attempts"] = 1
        expected = "unknown_attempts_changed_without_new_orders_sync"
    before = deepcopy(args)
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert expected in result["failed_checks"]
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False
    assert args == before


@pytest.mark.parametrize("kind", ["positions", "orders"])
def test_changed_inventory_with_advanced_sync_does_not_raise_sync_hold(kind):
    args = fixture()
    if kind == "positions":
        args[0]["open_notional"] = "1200"
        args[2]["account"]["open_notional"] = "1200"
        args[2]["positions_synced_at_ms"] += 1
        expected = "positions_changed_without_new_sync"
    else:
        args[2]["unresolved_attempts"] = 1
        args[2]["orders_synced_at_ms"] += 1
        expected = "unknown_attempts_changed_without_new_orders_sync"
    result = inspect(args)
    assert expected not in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_equal_numeric_exposure_with_different_decimal_spelling_is_not_new_inventory():
    args = fixture()
    args[0]["open_notional"] = "1000.0"
    args[2]["account"]["open_notional"] = "1000.0"
    result = inspect(args)
    assert "positions_changed_without_new_sync" not in result["failed_checks"]
    assert result["status"] == "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED"
    assert result["may_submit_real_order"] is False


def test_sync_guard_is_session_scoped_and_session_change_still_holds():
    args = fixture()
    args[2]["session_epoch"] += 1
    args[0]["open_risk"] = "60"
    args[2]["account"]["open_risk"] = "60"
    result = inspect(args)
    assert "positions_changed_without_new_sync" not in result["failed_checks"]
    assert "session_change_requires_external_reconciliation" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("change_source", [False, True])
def test_same_session_primary_instrument_switch_requires_external_evidence(change_source):
    args = fixture()
    args[1]["instrument"] = "WTIUSD"
    args[2]["risk_quote"]["instrument"] = "WTIUSD"
    if change_source:
        args[1]["source"] = "feedB"
        args[2]["risk_quote"]["source"] = "feedB"
    before = deepcopy(args)
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_SNAPSHOT_REVIEW"
    assert "quote_instrument_change_requires_external_evidence" in result["failed_checks"]
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False
    assert args == before


def test_primary_instrument_switch_during_new_session_still_holds_reconciliation():
    args = fixture()
    args[2]["session_epoch"] += 1
    args[1]["instrument"] = "WTIUSD"
    args[2]["risk_quote"]["instrument"] = "WTIUSD"
    result = inspect(args)
    assert "session_change_requires_external_reconciliation" in result["failed_checks"]
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("field", ["open_notional", "open_risk"])
def test_equal_numeric_exposure_without_new_revision_is_not_inventory_mutation(field):
    args = fixture()
    args[3]["positions_revision"] = args[2]["positions_revision"]
    args[0][field] = args[0][field] + ".0"
    args[2]["account"][field] = args[0][field]
    result = inspect(args)
    assert "positions_changed_without_revision" not in result["failed_checks"]
    assert "positions_changed_without_new_sync" not in result["failed_checks"]
    assert result["status"] == "DECLARED_ACCOUNT_SNAPSHOT_UNVERIFIED"
    assert result["may_submit_real_order"] is False
