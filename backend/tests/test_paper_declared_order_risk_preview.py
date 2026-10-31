"""Synthetic-only order risk preflight; no broker access or execution."""
from copy import deepcopy
import pytest
from app.paper_declared_order_risk_preview import inspect_declared_order_risk_preview

NOW = 1_800_000_000_000

def fixture():
    order = dict(client_order_id="order1", intent_sha="a"*64, instrument="XAUUSD", side="BUY", quantity="1", stop_price="95", requested_leverage="5")
    quote = dict(instrument="XAUUSD", source="paper-feed", bid="99.9", ask="100", observed_at_ms=NOW-100, received_at_ms=NOW-50)
    account = dict(broker="PAPER-LOCAL", account_alias="demo1", equity="10000", free_margin="5000", daily_realized_pnl="-100", open_notional="1000", open_risk="50", circuit_breaker_open=False)
    policy = dict(max_quote_age_ms=1000, max_transport_lag_ms=1000, max_spread_bps="100", max_slippage_bps="10", max_leverage="10", max_position_loss_pct="1", max_total_open_risk_pct="3", max_daily_loss_pct="5", max_notional_pct="200", max_order_quantity="10", max_orders_per_window=3, order_window_ms=1000)
    return [order, quote, account, policy, [], NOW]

def inspect(args):
    return inspect_declared_order_risk_preview(*args)

def test_safe_declared_preview_is_never_authorization():
    result=inspect(fixture())
    assert result["status"] == "DECLARED_RISK_PREVIEW_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["declared_margin_required"] == "20"
    assert result["may_submit_real_order"] is False
    assert result["may_submit_paper_order"] is False
    assert result["stop_guaranteed"] is False
    assert result["requires_individual_owner_approval"] is True

@pytest.mark.parametrize("category,key,value,check", [
    (0,"side","SELL","invalid_protective_stop"),
    (0,"stop_price","99.9","invalid_protective_stop"),
    (0,"stop_price","0.01","position_loss_limit"),
    (0,"requested_leverage","11","leverage_limit"),
    (0,"quantity","11","quantity_limit"),
    (1,"instrument","WTIUSD","quote_instrument_mismatch"),
    (1,"bid","100","invalid_quote_market"),
    (1,"ask","101","spread_limit"),
    (1,"observed_at_ms",NOW-2000,"stale_or_future_quote"),
    (1,"received_at_ms",NOW+1,"stale_or_future_quote"),
    (1,"received_at_ms",NOW-2000,"quote_transport_lag"),
    (2,"circuit_breaker_open",True,"circuit_breaker_open"),
    (2,"free_margin","1","insufficient_declared_margin"),
    (2,"open_notional","30000","gross_exposure_limit"),
    (2,"open_risk","300","portfolio_risk_limit"),
    (2,"daily_realized_pnl","-500","daily_loss_circuit_breaker"),
])
def test_fail_closed_risk_conditions(category,key,value,check):
    args=fixture()
    args[category][key]=value
    result=inspect(args)
    assert result["status"] == "HOLD_RISK_REVIEW"
    assert check in result["failed_checks"]
    assert result["may_submit_real_order"] is False

@pytest.mark.parametrize("category,key,value", [
    (0,"quantity",1), (0,"quantity","NaN"), (0,"quantity","0"),
    (0,"requested_leverage","0"), (0,"intent_sha","0"*64),
    (1,"bid","-1"), (1,"source",""),
    (2,"equity","0"), (2,"circuit_breaker_open",1),
    (3,"max_orders_per_window",True), (3,"max_quote_age_ms",False),
    (3,"max_slippage_bps","20000"), (3,"max_position_loss_pct","101"),
])
def test_invalid_inputs_raise(category,key,value):
    args=fixture()
    args[category][key]=value
    with pytest.raises(ValueError): inspect(args)

def test_duplicate_id_and_intent_hold_even_outside_rate_window():
    args=fixture()
    args[4]=[dict(client_order_id="order1",intent_sha="b"*64,submitted_at_ms=NOW-10000),dict(client_order_id="other",intent_sha="a"*64,submitted_at_ms=NOW-10000)]
    assert "duplicate_order_intent" in inspect(args)["failed_checks"]

def test_rate_limit_boundary():
    args=fixture()
    args[4]=[dict(client_order_id=f"order{i+2}",intent_sha=str(i+1)*64,submitted_at_ms=NOW-1000) for i in range(3)]
    assert "order_rate_limit" in inspect(args)["failed_checks"]

def test_future_order_history_holds():
    args=fixture()
    args[4]=[dict(client_order_id="order2",intent_sha="b"*64,submitted_at_ms=NOW+1)]
    assert "future_order_history" in inspect(args)["failed_checks"]

def test_sell_with_valid_stop():
    args=fixture()
    args[0].update(side="SELL",stop_price="105")
    assert inspect(args)["failed_checks"] == []

def test_inputs_not_mutated():
    args=fixture()
    before=deepcopy(args)
    inspect(args)
    assert args==before

def test_untrusted_policy_extra_field_rejected():
    args=fixture()
    args[3]["allow_live"]=True
    with pytest.raises(ValueError): inspect(args)

@pytest.mark.parametrize("repeat_field", ["client_order_id", "intent_sha"])
def test_conflicting_reused_history_identity_holds(repeat_field):
    args = fixture()
    first = dict(client_order_id="older1", intent_sha="b"*64, submitted_at_ms=NOW-20000)
    second = dict(client_order_id="older2", intent_sha="c"*64, submitted_at_ms=NOW-10000)
    second[repeat_field] = first[repeat_field]
    args[4] = [first, second]
    assert "duplicate_order_history" in inspect(args)["failed_checks"]


# T212 Public API: Invest/Stocks ISA are cash securities accounts, not CFDs.
# These are disconnected arithmetic tests, NOT instrument entitlement checks.
@pytest.mark.parametrize("broker", [
    "T212-INVEST-DEMO", "T212-STOCKSISA-DEMO",
    "T212-INVEST-LIVE", "T212-STOCKSISA-LIVE",
])
@pytest.mark.parametrize("requested,limit,side,stop,expected", [
    ("5", "10", "BUY", "95", {"cash_account_leverage_unsupported",
                             "cash_account_policy_leverage_unsupported"}),
    ("1", "10", "BUY", "95", {"cash_account_policy_leverage_unsupported"}),
    ("5", "1", "BUY", "95", {"cash_account_leverage_unsupported", "leverage_limit"}),
    ("1", "1", "SELL", "105", {"cash_account_sell_requires_authenticated_holdings"}),
    ("1", "1", "BUY", "95", set()),
])
def test_t212_cash_account_limits_never_authorize_orders(
    broker, requested, limit, side, stop, expected,
):
    args = fixture()
    args[2]["broker"] = broker
    args[0].update(requested_leverage=requested, side=side, stop_price=stop)
    args[3]["max_leverage"] = limit
    # A placeholder stock symbol avoids implying XAUUSD CFD entitlement.
    args[0]["instrument"] = args[1]["instrument"] = "EXAMPLE-STOCK"
    result = inspect(args)
    assert expected.issubset(set(result["failed_checks"]))
    assert (result["status"] == "HOLD_RISK_REVIEW") is bool(expected)
    assert result["broker_authenticated"] is False
    assert result["may_submit_paper_order"] is False
    assert result["may_submit_real_order"] is False


def test_paper_local_short_simulation_remains_disconnected():
    args = fixture()
    args[0].update(side="SELL", stop_price="105")
    result = inspect(args)
    assert result["failed_checks"] == []
    assert result["may_submit_real_order"] is False


def test_t212_cfd_label_cannot_be_used_to_claim_api_support():
    args = fixture()
    args[2]["broker"] = "T212-CFD-LIVE"
    with pytest.raises(ValueError, match="Unsupported broker"):
        inspect(args)


def test_t212_cash_account_check_does_not_mutate_inputs():
    args = fixture()
    args[2]["broker"] = "T212-INVEST-DEMO"
    before = deepcopy(args)
    inspect(args)
    assert args == before
