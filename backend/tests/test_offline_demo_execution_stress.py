"""Synthetic-only adverse execution regressions; never broker fills or P&L."""
from copy import deepcopy
from decimal import Decimal
import random

import pytest

from app.offline_demo_quote_tape_simulator import fingerprint_demo_quote_tape
from app.offline_demo_execution_stress import audit_declared_demo_execution_stress


def sample():
    scope = dict(
        provider="Synthetic", venue="DEMO", account_alias="test1",
        instrument="XAUUSD-CFD", quote_currency="USD", point_value_cash="1",
        max_quote_age_ms=100, max_spread_price="3",
        adverse_slippage_price="0.50",
        commission_per_contract_side="0.10", as_of_ms=1000,
    )
    intent = dict(
        client_order_id="order1", side="BUY", kind="MARKET",
        requested_contracts=5, limit_price=None, submitted_at_ms=100,
        eligible_after_ms=120, expires_at_ms=900,
        cancel_requested_at_ms=None, cancel_effective_at_ms=None,
    )
    quotes = [
        dict(quote_id="q1", provider="Synthetic", venue="DEMO",
             account_alias="test1", instrument="XAUUSD-CFD",
             observed_at_ms=140, received_at_ms=150, bid="100", ask="102",
             available_contracts=2),
        dict(quote_id="q2", provider="Synthetic", venue="DEMO",
             account_alias="test1", instrument="XAUUSD-CFD",
             observed_at_ms=160, received_at_ms=170, bid="101", ask="103",
             available_contracts=4),
    ]
    return scope, intent, quotes


def stress(name="mild", **changes):
    return dict(
        name=name, spread_widen_price="0.2",
        extra_adverse_slippage_price="0.25",
        depth_percent=100, quote_delivery_delay_ms=0, **changes,
    )


def run(scope=None, intent=None, quotes=None, stresses=None, digest=None):
    s, i, q = sample()
    s = s if scope is None else scope
    i = i if intent is None else intent
    q = q if quotes is None else quotes
    expected = fingerprint_demo_quote_tape(s, q) if digest is None else digest
    return audit_declared_demo_execution_stress(
        s, i, q, expected, [stress()] if stresses is None else stresses,
    )


def test_baseline_and_full_fill_adverse_cost_exact_and_no_execution():
    report = run()
    assert report["baseline"]["hypothetical_filled_contracts"] == 5
    assert report["baseline"]["total_entry_cost_cash"] == "8.00"
    assert report["stresses"][0]["hypothetical_filled_contracts"] == 5
    assert Decimal(report["stresses"][0]["spread_cost_cash"]) == Decimal("5.5")
    assert Decimal(report["stresses"][0]["adverse_slippage_cash"]) == Decimal("3.75")
    assert Decimal(report["stresses"][0]["commission_cash"]) == Decimal("0.50")
    assert Decimal(report["worst_comparable_full_fill_entry_cost_cash"]) == Decimal("9.75")
    assert report["all_scenarios_fully_filled"]
    assert not report["may_execute_real_order"]
    assert not report["may_execute_demo_order"]
    assert not report["verified_profitability"]
    assert not report["authenticated_market_data"]
    assert report == run()


def test_reduced_depth_cannot_mislead_using_lower_total_cost():
    spec = stress()
    spec.update(depth_percent=40, spread_widen_price="0",
                extra_adverse_slippage_price="0")
    report = run(stresses=[spec])
    assert report["baseline"]["hypothetical_filled_contracts"] == 5
    assert report["stresses"][0]["hypothetical_filled_contracts"] == 1
    assert report["minimum_hypothetical_filled_contracts"] == 1
    assert not report["all_scenarios_fully_filled"]
    assert report["worst_comparable_full_fill_entry_cost_cash"] is None
    assert Decimal(report["stresses"][0]["total_entry_cost_cash"]) < Decimal("8")


def test_delayed_quote_becomes_stale_without_invented_fill():
    spec = stress()
    spec.update(quote_delivery_delay_ms=120, spread_widen_price="0",
                extra_adverse_slippage_price="0")
    report = run(stresses=[spec])
    assert report["stresses"][0]["hypothetical_filled_contracts"] == 0
    assert report["stresses"][0]["status"] == "EXPIRED_UNFILLED"
    assert report["worst_comparable_full_fill_entry_cost_cash"] is None


def test_delivery_after_cutoff_is_not_fabricated():
    spec = stress()
    spec.update(quote_delivery_delay_ms=900, spread_widen_price="0",
                extra_adverse_slippage_price="0")
    report = run(stresses=[spec])
    assert report["stresses"][0]["derived_quote_count"] == 0
    assert report["stresses"][0]["hypothetical_fills"] == []


def test_cancellation_race_under_delayed_quotes():
    _, intent, _ = sample()
    intent.update(cancel_requested_at_ms=155, cancel_effective_at_ms=165)
    spec = stress()
    spec.update(quote_delivery_delay_ms=20, spread_widen_price="0",
                extra_adverse_slippage_price="0")
    report = run(intent=intent, stresses=[spec])
    assert report["baseline"]["hypothetical_filled_contracts"] == 2
    assert report["stresses"][0]["hypothetical_filled_contracts"] == 0
    assert report["stresses"][0]["status"] == "SYNTHETIC_CANCELED_UNFILLED"


def test_spread_threshold_blocks_derived_quotes():
    spec = stress()
    spec.update(spread_widen_price="2", extra_adverse_slippage_price="0")
    report = run(stresses=[spec])
    assert report["stresses"][0]["hypothetical_filled_contracts"] == 0


def test_limit_price_respected_after_stress():
    _, intent, _ = sample()
    intent.update(kind="LIMIT", limit_price="102.50")
    report = run(intent=intent)
    assert report["baseline"]["hypothetical_filled_contracts"] == 2
    assert report["stresses"][0]["hypothetical_filled_contracts"] == 0


def test_sell_side_widening_uses_lower_bid_and_adverse_slippage():
    _, intent, _ = sample()
    intent["side"] = "SELL"
    report = run(intent=intent)
    assert [Decimal(x["price"]) for x in report["stresses"][0]["hypothetical_fills"]] == [
        Decimal("99.15"), Decimal("100.15"),
    ]


def test_original_records_unchanged_and_order_independent_plan():
    s, i, q = sample()
    before = deepcopy((s, i, q))
    a = stress(name="alpha")
    b = stress(name="beta")
    a["depth_percent"] = 80
    b["quote_delivery_delay_ms"] = 10
    x = run(scope=s, intent=i, quotes=q, stresses=[b, a])
    y = run(scope=s, intent=i, quotes=q, stresses=[a, b])
    assert x == y
    assert [z["name"] for z in x["stresses"]] == ["alpha", "beta"]
    assert (s, i, q) == before
    assert x["stresses"][0]["quote_tape_sha256"] != x["baseline"]["quote_tape_sha256"]
    assert x["stresses"][0]["derived_only_not_authentic_quotes"]


def test_wrong_baseline_digest_rejected():
    with pytest.raises(ValueError, match="digest mismatch"):
        run(digest="f" * 64)


def test_cross_source_quote_rejected_before_stress():
    _, _, q = sample()
    q[0]["provider"] = "Another"
    with pytest.raises(ValueError, match="source"):
        run(quotes=q)


def test_nonpositive_bid_from_spread_stress_rejected():
    _, _, q = sample()
    q[0]["bid"] = "0.00000001"
    q[0]["ask"] = "2"
    q[1]["bid"] = "0.00000002"
    q[1]["ask"] = "2"
    spec = stress()
    with pytest.raises(ValueError, match="nonpositive bid"):
        run(quotes=q, stresses=[spec])


@pytest.mark.parametrize("field,value", [
    ("name", "baseline"), ("name", "bad name"), ("name", ""),
    ("spread_widen_price", "-1"), ("spread_widen_price", "1e-8"),
    ("spread_widen_price", "0.00000001"),
    ("spread_widen_price", 0.2), ("spread_widen_price", "NaN"),
    ("extra_adverse_slippage_price", "Infinity"),
    ("extra_adverse_slippage_price", -1),
    ("extra_adverse_slippage_price", "1001"),
    ("depth_percent", True), ("depth_percent", -1),
    ("depth_percent", 101), ("depth_percent", 50.5),
    ("quote_delivery_delay_ms", True), ("quote_delivery_delay_ms", -1),
    ("quote_delivery_delay_ms", 60001), ("quote_delivery_delay_ms", 2.1),
])
def test_malformed_stress_fails_closed(field, value):
    spec = stress()
    spec[field] = value
    with pytest.raises(ValueError):
        run(stresses=[spec])


def test_empty_duplicate_and_excessive_stresses_fail_closed():
    with pytest.raises(ValueError):
        run(stresses=[])
    with pytest.raises(ValueError):
        run(stresses=[stress(name="same"), stress(name="same")])
    with pytest.raises(ValueError):
        run(stresses=[stress(name=f"s{i}") for i in range(9)])


def test_nonadverse_noop_and_extra_field_fail_closed():
    spec = stress()
    spec.update(spread_widen_price="0", extra_adverse_slippage_price="0",
                depth_percent=100, quote_delivery_delay_ms=0)
    with pytest.raises(ValueError, match="worsen"):
        run(stresses=[spec])
    spec["hidden"] = "x"
    with pytest.raises(ValueError, match="schema"):
        run(stresses=[spec])


def test_exact_price_precision_no_exponent_and_stable_hash():
    s, _, q = sample()
    s["adverse_slippage_price"] = "0.00000001"
    spec = stress()
    spec.update(spread_widen_price="0.0000001",
                extra_adverse_slippage_price="0.00000001")
    result = run(scope=s, stresses=[spec])
    assert result["stresses"][0]["hypothetical_filled_contracts"] == 5
    assert result == run(scope=s, stresses=[spec])


def test_randomized_adverse_stress_invariants():
    rng = random.Random(174901)
    for _ in range(250):
        s, i, q = sample()
        i["requested_contracts"] = rng.randint(1, 10)
        q[0]["available_contracts"] = rng.randint(0, 10)
        q[1]["available_contracts"] = rng.randint(0, 10)
        spec = stress()
        spec.update(
            spread_widen_price=rng.choice(["0", "0.2", "1"]),
            extra_adverse_slippage_price=rng.choice(["0", "0.1"]),
            depth_percent=rng.randint(0, 99),
            quote_delivery_delay_ms=rng.choice([0, 10, 120, 900]),
        )
        result = run(scope=s, intent=i, quotes=q, stresses=[spec])
        base = result["baseline"]
        adverse = result["stresses"][0]
        assert sum(f["contracts"] for f in base["hypothetical_fills"]) == base["hypothetical_filled_contracts"]
        assert sum(f["contracts"] for f in adverse["hypothetical_fills"]) == adverse["hypothetical_filled_contracts"]
        assert 0 <= adverse["hypothetical_filled_contracts"] <= i["requested_contracts"]
        assert adverse["hypothetical_filled_contracts"] + adverse["remaining_contracts"] == i["requested_contracts"]
        assert result["minimum_hypothetical_filled_contracts"] == min(
            base["hypothetical_filled_contracts"], adverse["hypothetical_filled_contracts"])
        if not result["all_scenarios_fully_filled"]:
            assert result["worst_comparable_full_fill_entry_cost_cash"] is None
