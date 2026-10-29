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
    assert "risk_account_snapshot_mismatch" in inspect(args)["failed_checks"]


def test_quote_observed_after_received_holds():
    args = fixture()
    args[1]["observed_at_ms"] = NOW-50
    assert "invalid_quote_chronology" in inspect(args)["failed_checks"]
