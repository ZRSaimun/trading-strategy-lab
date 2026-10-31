"""Synthetic-only disconnected quote/risk binding tests. No network or orders."""
from copy import deepcopy
import pytest
from app.paper_declared_quote_risk_binding import inspect_declared_quote_risk_binding

NOW = 1_800_000_000_000


def fixture():
    order = dict(client_order_id="order1", intent_sha="a" * 64, instrument="XAUUSD", side="BUY", quantity="1", stop_price="95", requested_leverage="5")
    risk_quote = dict(instrument="XAUUSD", source="paper-feed", bid="99.9", ask="100", observed_at_ms=NOW - 100, received_at_ms=NOW - 50)
    account = dict(broker="PAPER-LOCAL", account_alias="demo1", equity="10000", free_margin="5000", daily_realized_pnl="-100", open_notional="1000", open_risk="50", circuit_breaker_open=False)
    risk_policy = dict(max_quote_age_ms=1000, max_transport_lag_ms=1000, max_spread_bps="100", max_slippage_bps="10", max_leverage="10", max_position_loss_pct="1", max_total_open_risk_pct="3", max_daily_loss_pct="5", max_notional_pct="200", max_order_quantity="10", max_orders_per_window=3, order_window_ms=1000)
    quote_sources = [deepcopy(risk_quote), dict(instrument="XAUUSD", source="other-feed", bid="99.91", ask="100.01", observed_at_ms=NOW - 110, received_at_ms=NOW - 60)]
    consensus_policy = dict(max_quote_age_ms=1000, max_transport_lag_ms=1000, max_inter_source_skew_ms=500, max_mid_divergence_bps="20", max_spread_bps="100")
    return [order, risk_quote, account, risk_policy, [], "paper-feed", quote_sources, consensus_policy, NOW]


def inspect(args):
    return inspect_declared_quote_risk_binding(*args)


def test_matching_declared_evidence_still_never_authorizes():
    result = inspect(fixture())
    assert result["status"] == "DECLARED_QUOTE_RISK_BINDING_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["risk_estimated_stop_loss_with_slippage"] == "5.1"
    for flag in ("quote_authenticated", "broker_authenticated", "source_independence_verified", "atomic_reservation_verified", "stop_guaranteed", "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False
    assert result["requires_individual_owner_approval"] is True


@pytest.mark.parametrize("key,value", [
    ("bid", "99.90"), ("ask", "100.00"),
    ("observed_at_ms", NOW - 101), ("received_at_ms", NOW - 51),
    ("source", "different"), ("instrument", "WTIUSD"),
])
def test_risk_quote_changed_from_primary_holds(key, value):
    args = fixture()
    args[1][key] = value
    assert inspect(args)["status"] == "HOLD_QUOTE_RISK_BINDING"


@pytest.mark.parametrize("key,value", [
    ("bid", "99.90"), ("ask", "100.00"),
    ("observed_at_ms", NOW - 101), ("received_at_ms", NOW - 51),
    ("source", "different"), ("instrument", "WTIUSD"),
])
def test_primary_quote_changed_from_risk_holds(key, value):
    args = fixture()
    args[6][0][key] = value
    assert inspect(args)["status"] == "HOLD_QUOTE_RISK_BINDING"


@pytest.mark.parametrize("key,value", [
    ("max_quote_age_ms", 1001),
    ("max_transport_lag_ms", 1001),
    ("max_spread_bps", "100.00000001"),
])
def test_consensus_policy_cannot_be_weaker(key, value):
    args = fixture()
    args[7][key] = value
    assert "weaker_consensus_" + key in inspect(args)["failed_checks"]


def test_stricter_consensus_policy_allowed():
    args = fixture()
    args[7].update(max_quote_age_ms=900, max_transport_lag_ms=900, max_spread_bps="50")
    assert inspect(args)["failed_checks"] == []


def test_consensus_divergence_holds_even_if_risk_is_clear():
    args = fixture()
    args[6][1].update(bid="101", ask="101.1")
    result = inspect(args)
    assert "quote_consensus_hold" in result["failed_checks"]
    assert "mid_price_divergence" in result["consensus_failed_checks"]


def test_risk_limit_holds_even_if_consensus_is_clear():
    args = fixture()
    args[2]["free_margin"] = "1"
    result = inspect(args)
    assert "risk_preview_hold" in result["failed_checks"]
    assert "insufficient_declared_margin" in result["risk_failed_checks"]


def test_missing_primary_holds():
    args = fixture()
    args[5] = "missing-feed"
    result = inspect(args)
    assert "primary_quote_not_unique" in result["failed_checks"]
    assert "quote_consensus_hold" in result["failed_checks"]


def test_duplicate_primary_holds():
    args = fixture()
    args[6][1]["source"] = "paper-feed"
    result = inspect(args)
    assert "primary_quote_not_unique" in result["failed_checks"]
    assert "quote_consensus_hold" in result["failed_checks"]


def test_no_input_mutation():
    args = fixture()
    before = deepcopy(args)
    inspect(args)
    assert args == before


@pytest.mark.parametrize("position,key,value", [
    (0, "quantity", "NaN"), (1, "bid", "0"),
    (3, "max_quote_age_ms", True), (7, "max_quote_age_ms", 0),
    (6, 0, None),
])
def test_invalid_evidence_raises(position, key, value):
    args = fixture()
    args[position][key] = value
    with pytest.raises(ValueError):
        inspect(args)
