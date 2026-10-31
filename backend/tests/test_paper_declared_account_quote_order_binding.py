"""Synthetic-only tests for composed account/quote/order safety fence."""
from copy import deepcopy

import pytest

from app.paper_declared_account_quote_order_binding import inspect_declared_account_quote_order_binding

NOW = 1_800_000_000_000


def fixture():
    order = dict(client_order_id="order1", intent_sha="a" * 64,
                 instrument="XAUUSD", side="BUY", quantity="1",
                 stop_price="95", requested_leverage="5")
    quote = dict(instrument="XAUUSD", source="feedA", bid="99.9", ask="100",
                 observed_at_ms=NOW-100, received_at_ms=NOW-50)
    account = dict(broker="PAPER-LOCAL", account_alias="demo1", equity="10000",
                   free_margin="5000", daily_realized_pnl="-100",
                   open_notional="1000", open_risk="50", circuit_breaker_open=False)
    risk_policy = dict(max_quote_age_ms=1000, max_transport_lag_ms=1000,
                       max_spread_bps="100", max_slippage_bps="10",
                       max_leverage="10", max_position_loss_pct="1",
                       max_total_open_risk_pct="3", max_daily_loss_pct="5",
                       max_notional_pct="200", max_order_quantity="10",
                       max_orders_per_window=3, order_window_ms=1000)
    sources = [deepcopy(quote), dict(instrument="XAUUSD", source="feedB",
               bid="99.91", ask="100.01", observed_at_ms=NOW-110,
               received_at_ms=NOW-60)]
    consensus = dict(max_quote_age_ms=1000, max_transport_lag_ms=1000,
                     max_inter_source_skew_ms=500,
                     max_mid_divergence_bps="20", max_spread_bps="100")
    current = dict(account=deepcopy(account), risk_quote=deepcopy(quote),
                   revision=12, session_epoch=2, positions_revision=5,
                   orders_revision=8, observed_at_ms=NOW-180,
                   received_at_ms=NOW-120, positions_synced_at_ms=NOW-200,
                   orders_synced_at_ms=NOW-220, reconciliation_complete=True,
                   unresolved_attempts=0)
    previous = deepcopy(current)
    previous.update(revision=11, positions_revision=4, orders_revision=7,
                    observed_at_ms=NOW-700, received_at_ms=NOW-600)
    snapshot_policy = dict(max_account_age_ms=1000,
                           max_account_transport_lag_ms=500,
                           max_quote_account_skew_ms=300,
                           max_positions_sync_age_ms=1000,
                           max_orders_sync_age_ms=1000)
    return [order, quote, account, risk_policy, [], "feedA", sources,
            consensus, current, previous, snapshot_policy, NOW]


def inspect(args):
    return inspect_declared_account_quote_order_binding(*args)


def test_clean_caller_declared_evidence_is_never_authorization():
    result = inspect(fixture())
    assert result["status"] == "DECLARED_ACCOUNT_QUOTE_ORDER_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["estimated_stop_loss_with_slippage"] == "5.1"
    for flag in ("broker_authenticated", "account_authenticated", "quote_authenticated",
                 "source_independence_verified", "external_reconciliation_verified",
                 "atomic_reservation_verified", "stop_guaranteed",
                 "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False
    assert result["requires_individual_owner_approval"] is True


def test_missing_previous_snapshot_holds():
    args = fixture()
    args[9] = None
    assert "missing_prior_account_snapshot" in inspect(args)["failed_checks"]


@pytest.mark.parametrize("position,key,value,check", [
    (1, "ask", "100.00", "quote_risk_binding_hold"),
    (2, "free_margin", "1", "quote_risk_binding_hold"),
    (6, "source", "unused", "quote_risk_binding_hold"),
    (8, "reconciliation_complete", False, "account_snapshot_fence_hold"),
    (8, "unresolved_attempts", 1, "account_snapshot_fence_hold"),
    (8, "session_epoch", 3, "account_snapshot_fence_hold"),
    (8, "positions_synced_at_ms", NOW-2000, "account_snapshot_fence_hold"),
])
def test_underlying_holds_propagate(position, key, value, check):
    args = fixture()
    if position == 6:
        args[6][0][key] = value
    else:
        args[position][key] = value
    result = inspect(args)
    assert check in result["failed_checks"]
    assert result["status"] == "HOLD_ACCOUNT_QUOTE_ORDER_BINDING"


@pytest.mark.parametrize("key,value,check", [
    ("max_account_age_ms", 1001, "weaker_account_freshness_policy"),
    ("max_account_transport_lag_ms", 1001, "weaker_account_transport_policy"),
    ("max_quote_account_skew_ms", 1001, "weaker_quote_account_skew_policy"),
    ("max_positions_sync_age_ms", 1001, "weaker_positions_sync_policy"),
    ("max_orders_sync_age_ms", 1001, "weaker_orders_sync_policy"),
])
def test_policy_weakening_holds(key, value, check):
    args = fixture()
    if key == "max_account_transport_lag_ms":
        args[3]["max_transport_lag_ms"] = 500
        args[10][key] = 501
    elif key == "max_quote_account_skew_ms":
        args[3]["max_quote_age_ms"] = 200
        args[10][key] = 300
    else:
        args[10][key] = value
    if key == "max_account_age_ms":
        args[3]["max_quote_age_ms"] = 900
        args[10][key] = 1000
    result = inspect(args)
    assert check in result["failed_checks"]


def test_circuit_breaker_reset_requires_external_evidence():
    args = fixture()
    args[9]["account"]["circuit_breaker_open"] = True
    assert "circuit_breaker_reset_requires_external_evidence" in inspect(args)["failed_checks"]


def test_reconciliation_release_requires_external_evidence():
    args = fixture()
    args[9]["reconciliation_complete"] = False
    assert "reconciliation_release_requires_external_evidence" in inspect(args)["failed_checks"]


def test_unknown_attempt_reduction_requires_external_evidence():
    args = fixture()
    args[9]["unresolved_attempts"] = 1
    assert "unknown_attempt_reduction_requires_external_evidence" in inspect(args)["failed_checks"]


def test_positions_changed_without_revision_holds():
    args = fixture()
    args[9]["positions_revision"] = args[8]["positions_revision"]
    args[9]["account"]["open_risk"] = "49"
    assert "positions_changed_without_revision" in inspect(args)["failed_checks"]


def test_unknown_attempts_changed_without_orders_revision_holds():
    args = fixture()
    args[9]["orders_revision"] = args[8]["orders_revision"]
    args[9]["unresolved_attempts"] = 1
    result = inspect(args)
    assert "unknown_attempts_changed_without_orders_revision" in result["failed_checks"]


def test_prior_circuit_breaker_still_open_holds():
    args = fixture()
    args[9]["account"]["circuit_breaker_open"] = True
    args[8]["account"]["circuit_breaker_open"] = True
    args[2]["circuit_breaker_open"] = True
    assert "account_snapshot_fence_hold" in inspect(args)["failed_checks"]


@pytest.mark.parametrize("position,key,value", [
    (0, "quantity", "NaN"), (1, "bid", "0"),
    (2, "equity", "0"), (8, "revision", True),
    (10, "max_account_age_ms", 3001),
])
def test_malformed_inputs_raise(position, key, value):
    args = fixture()
    args[position][key] = value
    with pytest.raises(ValueError):
        inspect(args)


def test_inputs_immutable():
    args = fixture()
    before = deepcopy(args)
    inspect(args)
    assert args == before


def test_inventory_sync_rollback_propagates_through_composed_review():
    args = fixture()
    args[8]["orders_synced_at_ms"] = NOW-221
    result = inspect(args)
    assert "account_snapshot_fence_hold" in result["failed_checks"]
    assert "orders_sync_time_rollback" in result["account_snapshot_failed_checks"]
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False


@pytest.mark.parametrize("field", ["open_notional", "open_risk"])
@pytest.mark.parametrize("equivalent", ["trailing_zero", "additional_zero"])
def test_composite_exposure_decimal_spelling_is_not_a_position_change(field, equivalent):
    args = fixture()
    args[9]["positions_revision"] = args[8]["positions_revision"]
    original = args[8]["account"][field]
    args[9]["account"][field] = original + (".0" if equivalent == "trailing_zero" else ".00")
    before = deepcopy(args)
    result = inspect(args)
    assert result["status"] == "DECLARED_ACCOUNT_QUOTE_ORDER_UNVERIFIED"
    assert "positions_changed_without_revision" not in result["failed_checks"]
    assert "positions_changed_without_revision" not in result["account_snapshot_failed_checks"]
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False
    assert args == before


@pytest.mark.parametrize("field,prior_value", [
    ("open_notional", "999.99"),
    ("open_risk", "49.99"),
])
def test_composite_still_holds_on_real_decimal_exposure_change(field, prior_value):
    args = fixture()
    args[9]["positions_revision"] = args[8]["positions_revision"]
    args[9]["account"][field] = prior_value
    result = inspect(args)
    assert result["status"] == "HOLD_ACCOUNT_QUOTE_ORDER_BINDING"
    assert "positions_changed_without_revision" in result["failed_checks"]
    assert "positions_changed_without_revision" in result["account_snapshot_failed_checks"]
    assert result["may_submit_real_order"] is False
