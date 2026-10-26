"""Synthetic offline scenario regressions. No authenticated broker data."""
import random

import pytest

from app.offline_demo_quote_tape_simulator import (
    fingerprint_demo_quote_tape, simulate_declared_demo_quote_tape,
)


def fixture():
    scope = dict(provider="Synthetic", venue="DEMO", account_alias="test1",
                 instrument="XAUUSD-CFD", quote_currency="USD", point_value_cash="1",
                 max_quote_age_ms=100, max_spread_price="3", adverse_slippage_price="0.50",
                 commission_per_contract_side="0.10", as_of_ms=1000)
    intent = dict(client_order_id="order1", side="BUY", kind="MARKET", requested_contracts=5,
                  limit_price=None, submitted_at_ms=100, eligible_after_ms=120,
                  expires_at_ms=900, cancel_requested_at_ms=None, cancel_effective_at_ms=None)
    quotes = [dict(quote_id="q1", provider="Synthetic", venue="DEMO", account_alias="test1",
                   instrument="XAUUSD-CFD", observed_at_ms=140, received_at_ms=150,
                   bid="100", ask="102", available_contracts=2),
              dict(quote_id="q2", provider="Synthetic", venue="DEMO", account_alias="test1",
                   instrument="XAUUSD-CFD", observed_at_ms=160, received_at_ms=170,
                   bid="101", ask="103", available_contracts=4)]
    return scope, intent, quotes


def run(scope=None, intent=None, quotes=None, expected=None):
    s, i, q = fixture()
    s = s if scope is None else scope
    i = i if intent is None else intent
    q = q if quotes is None else quotes
    return simulate_declared_demo_quote_tape(s, i, q,
        fingerprint_demo_quote_tape(s, q) if expected is None else expected)


def test_partial_depth_fills_costs_and_no_execution():
    x = run()
    assert x["status"] == "HYPOTHETICALLY_FILLED"
    assert x["hypothetical_filled_contracts"] == 5
    assert [f["contracts"] for f in x["fills"]] == [2, 3]
    assert [f["price"] for f in x["fills"]] == ["102.50", "103.50"]
    assert x["spread_cost_cash"] == "5"
    assert x["adverse_slippage_cash"] == "2.50"
    assert x["commission_cash"] == "0.50"
    assert x["total_entry_cost_cash"] == "8.00"
    assert not x["may_execute_real_order"] and not x["may_execute_demo_order"]
    assert run() == x


def test_short_uses_bid_minus_adverse_slippage():
    _, intent, _ = fixture()
    intent["side"] = "SELL"
    assert [f["price"] for f in run(intent=intent)["fills"]] == ["99.50", "100.50"]


def test_limit_uses_executable_price_including_slippage():
    _, intent, _ = fixture()
    intent.update(kind="LIMIT", limit_price="102.40")
    assert run(intent=intent)["status"] == "EXPIRED_UNFILLED"
    intent["limit_price"] = "102.50"
    x = run(intent=intent)
    assert x["hypothetical_filled_contracts"] == 2
    assert x["status"] == "EXPIRED_WITH_EXPOSURE"


def test_sell_limit_uses_executable_bid():
    _, intent, _ = fixture()
    intent.update(side="SELL", kind="LIMIT", limit_price="100")
    x = run(intent=intent)
    assert x["hypothetical_filled_contracts"] == 4
    assert x["status"] == "EXPIRED_WITH_EXPOSURE"


def test_cancel_request_does_not_erase_fill_and_effective_cancels_later():
    _, intent, _ = fixture()
    intent.update(cancel_requested_at_ms=155, cancel_effective_at_ms=165)
    x = run(intent=intent)
    assert x["status"] == "SYNTHETIC_CANCELED_WITH_EXPOSURE"
    assert x["hypothetical_filled_contracts"] == 2


def test_cancel_effective_tie_prevents_quote_fill():
    _, intent, _ = fixture()
    intent.update(cancel_requested_at_ms=130, cancel_effective_at_ms=150)
    assert run(intent=intent)["status"] == "SYNTHETIC_CANCELED_UNFILLED"


def test_expiry_tie_prevents_quote_fill():
    _, intent, _ = fixture()
    intent["expires_at_ms"] = 150
    assert run(intent=intent)["status"] == "EXPIRED_UNFILLED"


def test_stale_and_pre_submission_quote_cannot_fill():
    scope, intent, quotes = fixture()
    scope["max_quote_age_ms"] = 1
    assert run(scope=scope)["status"] == "EXPIRED_UNFILLED"
    intent["submitted_at_ms"] = 150
    intent["eligible_after_ms"] = 150
    assert run(intent=intent)["hypothetical_filled_contracts"] == 4


def test_spread_and_zero_depth_block_fill():
    scope, _, quotes = fixture()
    scope["max_spread_price"] = "1"
    assert run(scope=scope)["hypothetical_filled_contracts"] == 0
    for q in quotes:
        q["available_contracts"] = 0
    assert run(quotes=quotes)["hypothetical_filled_contracts"] == 0


def test_no_quote_unknown_not_fake_no_exposure():
    _, intent, _ = fixture()
    intent["expires_at_ms"] = 1500
    x = run(intent=intent, quotes=[])
    assert x["status"] == "PENDING_UNRESOLVED"
    assert x["fills"] == []


def test_partial_unknown_when_evaluation_precedes_expiry():
    scope, intent, _ = fixture()
    scope["as_of_ms"] = 155
    intent["expires_at_ms"] = 1500
    assert run(scope=scope, intent=intent, quotes=fixture()[2][:1])["status"] == "PARTIAL_UNRESOLVED"


def test_tape_digest_rejects_modified_data():
    scope, intent, quotes = fixture()
    h = fingerprint_demo_quote_tape(scope, quotes)
    quotes[0]["ask"] = "102.01"
    with pytest.raises(ValueError, match="digest mismatch"):
        run(scope=scope, intent=intent, quotes=quotes, expected=h)


@pytest.mark.parametrize("field,value", [
    ("max_quote_age_ms", 60001), ("max_quote_age_ms", True),
    ("as_of_ms", 2.5), ("quote_currency", "usd"),
    ("point_value_cash", "-1"), ("max_spread_price", "NaN"),
    ("adverse_slippage_price", "Infinity"), ("commission_per_contract_side", 0.1),
    ("provider", "bad source"),
])
def test_invalid_scope_fails_closed(field, value):
    scope, _, _ = fixture()
    scope[field] = value
    with pytest.raises(ValueError):
        run(scope=scope)


@pytest.mark.parametrize("field,value", [
    ("requested_contracts", True), ("requested_contracts", 0),
    ("side", "LONG"), ("kind", "STOP"), ("limit_price", "101"),
    ("submitted_at_ms", 1100), ("eligible_after_ms", 901),
    ("cancel_requested_at_ms", 200), ("client_order_id", "bad id"),
])
def test_invalid_intent_fails_closed(field, value):
    _, intent, _ = fixture()
    intent[field] = value
    with pytest.raises(ValueError):
        run(intent=intent)


@pytest.mark.parametrize("field,value", [
    ("available_contracts", True), ("available_contracts", -1),
    ("bid", "-100"), ("ask", "NaN"),
    ("received_at_ms", 1001), ("observed_at_ms", 151),
    ("provider", "Other"), ("quote_id", "bad id"),
])
def test_invalid_quote_fails_closed(field, value):
    _, _, quotes = fixture()
    quotes[0][field] = value
    with pytest.raises(ValueError):
        run(quotes=quotes)


def test_duplicate_quote_and_clock_reversal_fail():
    _, _, quotes = fixture()
    quotes[1]["quote_id"] = "q1"
    with pytest.raises(ValueError):
        run(quotes=quotes)
    _, _, quotes = fixture()
    quotes[1]["observed_at_ms"] = 139
    with pytest.raises(ValueError):
        run(quotes=quotes)


def test_crossed_quote_and_extra_fields_fail():
    _, _, quotes = fixture()
    quotes[0]["bid"] = "103"
    with pytest.raises(ValueError):
        run(quotes=quotes)
    _, _, quotes = fixture()
    quotes[0]["extra"] = "hidden"
    with pytest.raises(ValueError):
        run(quotes=quotes)


def test_tape_bound_and_expected_hash_validation():
    scope, intent, quotes = fixture()
    with pytest.raises(ValueError):
        run(scope=scope, intent=intent, quotes=quotes, expected="a" * 64)
    with pytest.raises(ValueError):
        run(quotes=[quotes[0]] * 2001)


def test_randomized_cost_accounting_and_partial_fill_bound():
    rng = random.Random(14723)
    for _ in range(250):
        scope, intent, quotes = fixture()
        scope["adverse_slippage_price"] = str(rng.randint(0, 10) / 10)
        scope["commission_per_contract_side"] = str(rng.randint(0, 10) / 10)
        intent["requested_contracts"] = rng.randint(1, 10)
        quotes[0]["available_contracts"] = rng.randint(0, 10)
        quotes[1]["available_contracts"] = rng.randint(0, 10)
        x = run(scope=scope, intent=intent, quotes=quotes)
        assert sum(f["contracts"] for f in x["fills"]) == x["hypothetical_filled_contracts"]
        assert x["remaining_contracts"] + x["hypothetical_filled_contracts"] == intent["requested_contracts"]
        from decimal import Decimal
        assert (Decimal(x["spread_cost_cash"]) + Decimal(x["adverse_slippage_cash"]) +
                Decimal(x["commission_cash"]) == Decimal(x["total_entry_cost_cash"]))
