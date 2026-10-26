"""Synthetic, disconnected risk tests; never touch a broker or persistent owner data."""
from copy import deepcopy
import re

import pytest

from app.paper_portfolio_concentration_guard import evaluate_portfolio_concentration

NOW = 1_790_000_000_000


def position(**changes):
    p = {
        "position_id": "open-position-01", "instrument": "XAUUSD",
        "risk_group": "METALS", "side": "BUY",
        "gross_notional_cash": "1000", "stressed_loss_cash": "100",
        "margin_cash": "500", "quote_observed_ms": NOW - 200,
        "quote_received_ms": NOW - 100, "quote_id": "quote-001",
    }
    p.update(changes)
    return p


def snapshot():
    return {
        "account_alias": "paper-account", "provider": "Trading212-Invest",
        "currency": "GBP", "equity_cash": "10000",
        "limits": {
            "max_position_stress_cash": "200",
            "max_group_stress_cash": "500",
            "max_portfolio_stress_cash": "1000",
            "max_symbol_notional_cash": "2000",
            "max_group_notional_cash": "4000",
            "max_gross_notional_cash": "8000",
            "max_margin_cash": "4000",
            "max_leverage": "1",
            "group_shock_multiplier": "1.5",
        },
        "positions": [position()],
        "candidate": position(
            position_id="candidate-002", instrument="XAGUSD",
            gross_notional_cash="500", stressed_loss_cash="50",
            margin_cash="250", quote_id="quote-002"
        ),
        "inventory_observed_ms": NOW - 250,
        "inventory_received_ms": NOW - 100,
        "inventory_complete": True,
    }


def evaluate(s=None, now=NOW):
    return evaluate_portfolio_concentration(s if s is not None else snapshot(),
                                             now_ms=now)


def test_baseline_passes_assumptions_but_never_authorizes_orders():
    s = snapshot()
    original = deepcopy(s)
    result = evaluate(s)
    assert result["assumption_checks_pass"]
    assert result["failed_checks"] == []
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["may_execute_real_order"] is False
    assert result["may_execute_paper_order"] is False
    assert not result["inventory_authenticated"]
    assert not result["owner_approval_recorded"]
    assert s == original


def test_gross_stress_has_no_hedge_offset_and_shocks_all_positions():
    s = snapshot()
    s["candidate"]["side"] = "SELL"
    s["candidate"]["instrument"] = "XAUUSD"
    result = evaluate(s)
    assert result["summary"]["gross_notional_cash"] == "1500"
    assert result["summary"]["declared_base_stress_loss_cash"] == "150"
    assert result["summary"]["correlated_shock_loss_cash"] == "225.0"
    assert result["summary"]["group_shock_loss_cash"]["METALS"] == "225.0"


@pytest.mark.parametrize("path,value,failed", [
    (("candidate", "stressed_loss_cash"), "150", "position_stress_within_cap"),
    (("positions", 0, "stressed_loss_cash"), "300", "every_group_stress_within_cap"),
    (("positions", 0, "stressed_loss_cash"), "650", "portfolio_stress_within_cap"),
    (("candidate", "gross_notional_cash"), "3500", "every_group_notional_within_cap"),
    (("candidate", "gross_notional_cash"), "7500", "gross_notional_within_cap"),
    (("candidate", "margin_cash"), "3800", "margin_within_cap_and_equity"),
    (("limits", "max_leverage"), "0.1", "gross_leverage_within_cap"),
    (("limits", "max_position_stress_cash"), "600", "policy_caps_consistent"),
    (("limits", "max_margin_cash"), "12000", "policy_caps_consistent"),
    (("inventory_complete",), False, "inventory_declared_complete"),
    (("inventory_observed_ms",), NOW - 5000, "inventory_fresh"),
    (("inventory_received_ms",), NOW + 1, "inventory_timestamp_order"),
    (("candidate", "quote_observed_ms"), NOW - 5000, "all_quotes_fresh"),
    (("candidate", "quote_received_ms"), NOW + 1, "all_quote_timestamps_ordered"),
    (("positions", 0, "quote_received_ms"), NOW - 2000, "all_quote_timestamps_ordered"),
    (("provider",), "Trading212-CFD", "supported_public_api_account"),
    (("candidate", "position_id"), "open-position-01", "distinct_position_ids"),
])
def test_fail_closed_scenarios(path, value, failed):
    s = snapshot()
    node = s
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    r = evaluate(s)
    assert failed in r["failed_checks"]
    assert not r["assumption_checks_pass"]
    assert not r["may_execute_real_order"]


def test_symbol_concentration_counts_opposing_sides():
    s = snapshot()
    s["candidate"]["instrument"] = "XAUUSD"
    s["candidate"]["side"] = "SELL"
    s["candidate"]["gross_notional_cash"] = "1500"
    r = evaluate(s)
    assert "every_symbol_notional_within_cap" in r["failed_checks"]
    assert r["summary"]["symbol_gross_notional_cash"]["XAUUSD"] == "2500"


def test_post_stress_equity_must_cover_margin():
    s = snapshot()
    s["equity_cash"] = "1000"
    s["candidate"]["margin_cash"] = "400"
    r = evaluate(s)
    assert "post_stress_equity_covers_margin" in r["failed_checks"]


def test_duplicate_existing_ids_rejected():
    s = snapshot()
    s["positions"].append(deepcopy(s["positions"][0]))
    assert "distinct_position_ids" in evaluate(s)["failed_checks"]


def test_untrusted_stale_quote_cannot_be_relabelled_as_fresh():
    s = snapshot()
    s["candidate"]["quote_observed_ms"] = NOW - 2500
    s["candidate"]["quote_received_ms"] = NOW - 100
    assert "all_quote_transport_fresh" in evaluate(s)["failed_checks"]


@pytest.mark.parametrize("path,value", [
    (("equity_cash",), 10000.0),
    (("equity_cash",), "1e4"),
    (("equity_cash",), "-1"),
    (("equity_cash",), "0"),
    (("equity_cash",), "NaN"),
    (("equity_cash",), "10000.000000001"),
    (("equity_cash",), " 10000"),
    (("limits", "max_leverage"), "6"),
    (("limits", "group_shock_multiplier"), "0.9"),
    (("limits", "group_shock_multiplier"), "5.01"),
    (("candidate", "stressed_loss_cash"), "0"),
    (("candidate", "margin_cash"), "0"),
    (("candidate", "side"), "SHORT"),
    (("candidate", "quote_observed_ms"), True),
    (("currency",), "gbp"),
    (("inventory_complete",), 1),
    (("account_alias",), "bad alias"),
])
def test_invalid_or_unbounded_inputs_rejected(path, value):
    s = snapshot()
    node = s
    for part in path[:-1]:
        node = node[part]
    node[path[-1]] = value
    with pytest.raises(ValueError):
        evaluate(s)


def test_extra_and_missing_fields_rejected():
    s = snapshot()
    s["secret"] = "should-not-be-accepted"
    with pytest.raises(ValueError):
        evaluate(s)
    s = snapshot()
    del s["candidate"]["quote_id"]
    with pytest.raises(ValueError):
        evaluate(s)
    s = snapshot()
    s["limits"]["unexpected"] = "100"
    with pytest.raises(ValueError):
        evaluate(s)


def test_positions_list_bound_and_server_clock():
    s = snapshot()
    s["positions"] = [position(position_id=f"position-{i:03d}") for i in range(51)]
    with pytest.raises(ValueError):
        evaluate(s)
    with pytest.raises(ValueError):
        evaluate(now=True)
    with pytest.raises(ValueError):
        evaluate(now=NOW + 9_000_000_000_000_000)


def test_diagnostic_hash_binds_quote_risk_and_account_but_is_not_approval():
    baseline = evaluate()
    assert re.fullmatch(r"[0-9a-f]{64}", baseline["review_sha256"])
    assert evaluate()["review_sha256"] == baseline["review_sha256"]
    for section, key, value in [
        ("candidate", "quote_id", "quote-999"),
        ("candidate", "risk_group", "OTHER"),
        ("limits", "max_group_stress_cash", "490"),
    ]:
        s = snapshot()
        s[section][key] = value
        assert evaluate(s)["review_sha256"] != baseline["review_sha256"]
    s = snapshot()
    s["account_alias"] = "another-paper-account"
    assert evaluate(s)["review_sha256"] != baseline["review_sha256"]
    assert evaluate(now=NOW + 1)["review_sha256"] != baseline["review_sha256"]
    assert baseline["may_execute_real_order"] is False


def test_cash_values_preserve_exact_decimal_boundaries():
    s = snapshot()
    s["limits"]["max_position_stress_cash"] = "75"
    assert evaluate(s)["checks"]["position_stress_within_cap"]
    s["limits"]["max_position_stress_cash"] = "74.99999999"
    assert not evaluate(s)["checks"]["position_stress_within_cap"]
