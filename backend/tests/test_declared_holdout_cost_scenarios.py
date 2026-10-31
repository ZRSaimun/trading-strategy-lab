"""Synthetic-only adverse-cost scenario tests; no market or broker data."""
import copy
from decimal import Decimal

import pytest

from app.declared_holdout_cost_scenarios import audit_declared_holdout_cost_scenarios
from test_declared_holdout_cost_attribution import _fixture


def _scenario(name="adverse", spread="0.5000", slip="0.2500",
              commission="0.1000", financing="0.2000", fx="0.0500"):
    return {
        "scenario_id": name,
        "spread_extra_cash_per_observation": spread,
        "slippage_extra_cash_per_observation": slip,
        "commission_extra_cash_per_observation": commission,
        "financing_extra_cash_per_observation": financing,
        "fx_extra_cash_per_observation": fx,
    }


def _audit(data, scenarios):
    return audit_declared_holdout_cost_scenarios(*data, scenarios)


def test_exact_adverse_debits_and_worst_scenario():
    data = _fixture()
    before = copy.deepcopy(data)
    scenarios = [_scenario("severe"), _scenario("mild", spread="0.0000",
                                                  slip="0.0000",
                                                  commission="0.0000",
                                                  financing="0.0000",
                                                  fx="0.0000")]
    result = _audit(data, scenarios)
    assert result["status"] == "DECLARED_EVALUATION_ONLY"
    assert result["baseline_net_cash"] == "54.0000"
    assert result["scenarios"] == [
        {"scenario_id": "mild", "extra_cost_cash": "0.0000",
         "stressed_net_cash": "54.0000"},
        {"scenario_id": "severe", "extra_cost_cash": "33.0000",
         "stressed_net_cash": "21.0000"},
    ]
    assert result["worst_scenario_id"] == "severe"
    assert result["worst_stressed_net_cash"] == "21.0000"
    assert data == before and scenarios[0] == _scenario("severe")
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False


@pytest.mark.parametrize("count", [1, 29])
def test_small_holdout_never_reveals_costs_or_receipts(count):
    result = _audit(_fixture(count), [_scenario()])
    assert result["outcome_metrics_withheld"] is True
    assert result["baseline_net_cash"] is None
    assert result["outcome_receipts_sha256"] is None
    assert result["worst_scenario_id"] is None
    assert result["worst_stressed_net_cash"] is None
    assert result["scenarios"][0]["extra_cost_cash"] is None
    assert result["scenarios"][0]["stressed_net_cash"] is None


def test_stress_is_monotone_and_exact_for_10000_observations_not_required():
    data = _fixture()
    low = _audit(data, [_scenario(spread="0.0001")])
    high = _audit(data, [_scenario(spread="0.0002")])
    assert Decimal(low["scenarios"][0]["stressed_net_cash"]) - Decimal(
        high["scenarios"][0]["stressed_net_cash"]) == Decimal("0.0030")


def test_tied_worst_scenario_uses_lexical_id():
    result = _audit(_fixture(), [_scenario("z"), _scenario("a")])
    assert result["worst_scenario_id"] == "a"


def test_permutation_invariance():
    data = _fixture()
    result = _audit(data, [_scenario("z"), _scenario("a")])
    reversed_data = copy.deepcopy(data)
    reversed_data[3].reverse()
    assert _audit(reversed_data, [_scenario("a"), _scenario("z")]) == result


@pytest.mark.parametrize("scenarios", [
    [], [_scenario(str(i)) for i in range(9)],
    [_scenario("dup"), _scenario("dup")],
    [_scenario(spread="-0.0001")],
    [_scenario(slip="NaN")],
    [_scenario(financing="1e4")],
    [_scenario(fx=0.1)],
    [_scenario(commission="-0.0000")],
    [{**_scenario(), "order_permission": True}],
    [{k: v for k, v in _scenario().items() if k !=
      "fx_extra_cash_per_observation"}],
])
def test_malformed_or_unsafe_scenarios_fail_closed(scenarios):
    with pytest.raises(ValueError):
        _audit(_fixture(), scenarios)


def test_source_mismatch_still_rejected_before_scenarios():
    data = _fixture()
    data[3][0]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        _audit(data, [_scenario()])


def test_premature_release_still_rejected():
    data = list(_fixture())
    data[4] = data[0]["holdout_end_at_utc"] - 1
    with pytest.raises(ValueError):
        _audit(tuple(data), [_scenario()])
