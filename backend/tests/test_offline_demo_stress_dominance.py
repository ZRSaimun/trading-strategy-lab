"""Synthetic-only adversarial checks; no broker orders, actual prices or P&L."""
from copy import deepcopy
from decimal import Decimal
import random

import pytest

from app.offline_demo_quote_tape_simulator import fingerprint_demo_quote_tape
from app.offline_demo_stress_dominance import audit_declared_demo_stress_dominance
from app import offline_demo_stress_dominance as guard


def sample(side="BUY"):
    scope = dict(provider="Synthetic", venue="DEMO", account_alias="test1",
                 instrument="XAUUSD-CFD", quote_currency="USD", point_value_cash="1",
                 max_quote_age_ms=100, max_spread_price="3",
                 adverse_slippage_price="0.50", commission_per_contract_side="0.10",
                 as_of_ms=1000)
    intent = dict(client_order_id="order1", side=side, kind="MARKET",
                  requested_contracts=5, limit_price=None, submitted_at_ms=100,
                  eligible_after_ms=120, expires_at_ms=900,
                  cancel_requested_at_ms=None, cancel_effective_at_ms=None)
    quotes = [dict(quote_id=f"q{idx}", provider="Synthetic", venue="DEMO",
                   account_alias="test1", instrument="XAUUSD-CFD",
                   observed_at_ms=140 + idx * 20,
                   received_at_ms=150 + idx * 20,
                   bid=str(100 + idx), ask=str(102 + idx),
                   available_contracts=depth)
              for idx, depth in enumerate((2, 4))]
    return scope, intent, quotes


def stress(name="mild", spread="0.2", slip="0.25", depth=100, delay=0):
    return dict(name=name, spread_widen_price=spread,
                extra_adverse_slippage_price=slip, depth_percent=depth,
                quote_delivery_delay_ms=delay)


def run(scope=None, intent=None, quotes=None, stresses=None, digest=None):
    s, i, q = sample()
    s = s if scope is None else scope
    i = i if intent is None else intent
    q = q if quotes is None else quotes
    digest = fingerprint_demo_quote_tape(s, q) if digest is None else digest
    return audit_declared_demo_stress_dominance(
        s, i, q, digest, [stress()] if stresses is None else stresses,
    )


def test_full_fill_envelope_and_no_execution_permissions():
    result = run()
    assert result["baseline_hypothetical_filled_contracts"] == 5
    assert result["minimum_hypothetical_filled_contracts"] == 5
    assert result["maximum_unfilled_contracts"] == 0
    assert result["minimum_fill_fraction"] == "5/5"
    assert Decimal(result["worst_comparable_full_fill_entry_cost_cash"]) == Decimal("9.75")
    assert result["quote_lineage_and_cash_invariants_checked"]
    assert not result["independently_authenticated_quotes"]
    assert not result["actual_liquidity_verified"]
    assert not result["verified_profitability"]
    assert not result["may_execute_demo_order"]
    assert not result["may_execute_real_order"]
    assert result == run()


def test_underfill_withholds_comparable_cost_and_reports_worst_scenario():
    result = run(stresses=[stress(name="depth", spread="0", slip="0", depth=40),
                           stress(name="latency", spread="0", slip="0", delay=900)])
    assert result["minimum_hypothetical_filled_contracts"] == 0
    assert result["maximum_unfilled_contracts"] == 5
    assert result["minimum_fill_fraction"] == "0/5"
    assert result["worst_fill_scenarios"] == ["latency"]
    assert result["worst_comparable_full_fill_entry_cost_cash"] is None
    assert not result["all_scenarios_fully_filled"]


def test_sell_side_adverse_quotes_and_partial_cancellation():
    s, i, q = sample("SELL")
    i.update(cancel_requested_at_ms=155, cancel_effective_at_ms=165)
    result = run(s, i, q, [stress(delay=20)])
    assert result["baseline_hypothetical_filled_contracts"] == 2
    assert result["minimum_hypothetical_filled_contracts"] == 0


def test_invalid_baseline_digest_and_cross_source_rejected():
    with pytest.raises(ValueError, match="digest mismatch"):
        run(digest="a" * 64)
    s, i, q = sample()
    q[0]["provider"] = "Unrelated"
    with pytest.raises(ValueError):
        run(s, i, q)


def test_no_mutation_and_order_independent_stress_plan():
    s, i, q = sample()
    original = deepcopy((s, i, q))
    a = stress(name="alpha", depth=60)
    b = stress(name="beta", delay=15)
    x = run(s, i, q, [a, b])
    y = run(s, i, q, [b, a])
    assert x == y
    assert (s, i, q) == original


@pytest.mark.parametrize("mutator,pattern", [
    (lambda r: r["stresses"][0].update(hypothetical_filled_contracts=6), "quantity"),
    (lambda r: r["stresses"][0]["hypothetical_fills"][0].update(price="1"), "price"),
    (lambda r: r["stresses"][0]["hypothetical_fills"][0].update(at_ms=1), "receipt"),
    (lambda r: r["stresses"][0]["hypothetical_fills"][0].update(quote_id="forged"), "quote identity"),
    (lambda r: r["stresses"][0]["hypothetical_fills"][0].update(contracts=100), "depth"),
    (lambda r: r["stresses"][0].update(derived_quote_count=100), "population"),
    (lambda r: r["stresses"][0].update(total_entry_cost_cash="0"), "decomposition"),
    (lambda r: r.update(minimum_hypothetical_filled_contracts=999), "summary"),
    (lambda r: r.update(all_scenarios_fully_filled=False), "summary"),
    (lambda r: r.update(worst_comparable_full_fill_entry_cost_cash="0"), "envelope"),
])
def test_adversarial_internal_result_mutations_fail_closed(monkeypatch, mutator, pattern):
    original = guard.engine.audit_declared_demo_execution_stress

    def corrupted(*args, **kwargs):
        result = deepcopy(original(*args, **kwargs))
        mutator(result)
        return result

    monkeypatch.setattr(guard.engine, "audit_declared_demo_execution_stress", corrupted)
    with pytest.raises(ValueError, match=pattern):
        run()


def test_randomized_adverse_dominance_invariants():
    rng = random.Random(881993)
    for _ in range(250):
        s, i, q = sample(rng.choice(["BUY", "SELL"]))
        i["requested_contracts"] = rng.randint(1, 10)
        q[0]["available_contracts"] = rng.randint(0, 10)
        q[1]["available_contracts"] = rng.randint(0, 10)
        plan = [stress(spread=rng.choice(["0", "0.2", "1"]),
                       slip=rng.choice(["0", "0.1", "0.5"]),
                       depth=rng.randint(0, 99),
                       delay=rng.choice([0, 10, 120, 900]))]
        result = run(s, i, q, plan)
        assert result["minimum_hypothetical_filled_contracts"] <= result["baseline_hypothetical_filled_contracts"]
        assert result["minimum_hypothetical_filled_contracts"] + result["maximum_unfilled_contracts"] == i["requested_contracts"]
        assert not result["may_execute_real_order"]
        assert not result["verified_profitability"]
