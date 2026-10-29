"""Synthetic-only, row-specific adverse cost stress regressions."""
import copy
from decimal import Decimal

import pytest

from app.declared_holdout_row_cost_stress import (
    audit_declared_holdout_row_cost_stress,
)
from test_declared_holdout_cost_attribution import _fixture

_COSTS = (
    "spread_extra_cash", "slippage_extra_cash", "commission_extra_cash",
    "financing_extra_cash", "fx_extra_cash",
)


def _scenario(data, name="stress", per_row=None):
    per_row = per_row or {}
    adjustments = []
    for i, row in enumerate(data[1]):
        adjustment = {
            "observation_id": row["observation_id"],
            "row_sha256": row["row_sha256"],
            "source_sha256": row["source_sha256"],
            **{field: "0.0000" for field in _COSTS},
        }
        adjustment.update(per_row.get(i, {}))
        adjustments.append(adjustment)
    return {"scenario_id": name, "adjustments": adjustments}


def _audit(data, scenarios):
    return audit_declared_holdout_row_cost_stress(*data, scenarios)


def test_row_specific_components_and_maximum_reconcile():
    data = _fixture()
    original = copy.deepcopy(data)
    scenario = _scenario(data, per_row={
        0: {"spread_extra_cash": "1.2500"},
        1: {"financing_extra_cash": "0.7500"},
    })
    report = _audit(data, [scenario])
    assert report["status"] == "DECLARED_EVALUATION_ONLY"
    assert report["baseline_net_cash"] == "54.0000"
    assert report["scenarios"][0] == {
        "scenario_id": "stress",
        "extra_cost_cash": "2.0000",
        "stressed_net_cash": "52.0000",
        "max_single_observation_extra_cost_cash": "1.2500",
        "extra_cost_by_component_cash": {
            "spread_extra_cash": "1.2500",
            "slippage_extra_cash": "0.0000",
            "commission_extra_cash": "0.0000",
            "financing_extra_cash": "0.7500",
            "fx_extra_cash": "0.0000",
        },
    }
    assert report["worst_scenario_id"] == "stress"
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False
    assert report["broker_costs_verified"] is False
    assert data == original


def test_zero_costs_preserve_baseline_and_do_not_verify_edge():
    data = _fixture()
    result = _audit(data, [_scenario(data)])
    assert result["scenarios"][0]["extra_cost_cash"] == "0.0000"
    assert result["scenarios"][0]["stressed_net_cash"] == "54.0000"
    assert result["profitable_edge_verified"] is False


@pytest.mark.parametrize("count", [1, 29])
def test_small_holdout_withholds_all_outcome_and_cost_metrics(count):
    data = _fixture(count)
    scenario = _scenario(data, per_row={
        0: {"spread_extra_cash": "9.0000"},
    })
    before = _audit(data, [scenario])
    changed = copy.deepcopy(data)
    for row in changed[3]:
        row["gross_cash"] = "-999.0000"
        row["receipt_sha256"] = "e" * 64  # fixed below for uniqueness
    for i, row in enumerate(changed[3]):
        row["receipt_sha256"] = f"{i + 2000:064x}"
    after = _audit(changed, [scenario])
    assert before == after
    assert before["outcome_metrics_withheld"] is True
    assert before["baseline_net_cash"] is None
    assert before["outcome_receipts_sha256"] is None
    assert before["worst_scenario_id"] is None
    assert before["worst_stressed_net_cash"] is None
    entry = before["scenarios"][0]
    assert entry["extra_cost_cash"] is None
    assert entry["stressed_net_cash"] is None
    assert entry["max_single_observation_extra_cost_cash"] is None
    assert all(value is None for value in entry["extra_cost_by_component_cash"].values())


def test_exact_30_observation_boundary_releases_only_declared_metrics():
    data = _fixture(30)
    result = _audit(data, [_scenario(data)])
    assert result["outcome_metrics_withheld"] is False
    assert result["broker_costs_verified"] is False


def test_scenario_and_adjustment_order_do_not_change_result():
    data = _fixture()
    first = _scenario(data, "b", {0: {"fx_extra_cash": "0.0001"}})
    second = _scenario(data, "a", {4: {"commission_extra_cash": "0.0002"}})
    expected = _audit(data, [first, second])
    shuffled = copy.deepcopy(data)
    shuffled[3].reverse()
    reordered = copy.deepcopy([second, first])
    for scenario in reordered:
        scenario["adjustments"].reverse()
    assert _audit(shuffled, reordered) == expected
    assert expected["worst_scenario_id"] == "a"


def test_tied_worst_uses_lexical_scenario_id():
    data = _fixture()
    assert _audit(data, [_scenario(data, "z"), _scenario(data, "a")])[
        "worst_scenario_id"
    ] == "a"


def test_monotone_cost_stress_and_no_rounding_drift():
    data = _fixture()
    low = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "0.0001"},
    })])
    high = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "0.0002"},
    })])
    assert Decimal(low["worst_stressed_net_cash"]) - Decimal(
        high["worst_stressed_net_cash"]
    ) == Decimal("0.0001")


@pytest.mark.parametrize("mutation", [
    lambda s: s["adjustments"].pop(),
    lambda s: s["adjustments"].append(copy.deepcopy(s["adjustments"][0])),
    lambda s: s["adjustments"].__setitem__(1, copy.deepcopy(s["adjustments"][0])),
    lambda s: s["adjustments"][0].update(observation_id="missing"),
    lambda s: s["adjustments"][0].update(row_sha256="f" * 64),
    lambda s: s["adjustments"][0].update(source_sha256="f" * 64),
    lambda s: s["adjustments"][0].update(spread_extra_cash="-0.0001"),
    lambda s: s["adjustments"][0].update(financing_extra_cash="-0.0000"),
    lambda s: s["adjustments"][0].update(fx_extra_cash="NaN"),
    lambda s: s["adjustments"][0].update(slippage_extra_cash="1e5"),
    lambda s: s["adjustments"][0].update(commission_extra_cash="0.00001"),
    lambda s: s["adjustments"][0].update(commission_extra_cash=0.1),
    lambda s: s["adjustments"][0].update(commission_extra_cash=True),
    lambda s: s["adjustments"][0].update(order_permission=True),
    lambda s: s["adjustments"][0].pop("fx_extra_cash"),
    lambda s: s.update(order_permission=True),
    lambda s: s.update(scenario_id=""),
    lambda s: s.update(adjustments=tuple(s["adjustments"])),
])
def test_malformed_row_scenarios_fail_closed(mutation):
    data = _fixture()
    scenario = _scenario(data)
    mutation(scenario)
    with pytest.raises(ValueError):
        _audit(data, [scenario])


@pytest.mark.parametrize("bad", [
    [],
    [None],
    "scenario",
])
def test_invalid_scenario_collections_rejected(bad):
    with pytest.raises(ValueError):
        _audit(_fixture(), bad)


def test_duplicate_ids_and_too_many_scenarios_rejected():
    data = _fixture()
    with pytest.raises(ValueError):
        _audit(data, [_scenario(data, "x"), _scenario(data, "x")])
    with pytest.raises(ValueError):
        _audit(data, [_scenario(data, str(i)) for i in range(9)])


def test_underlying_source_and_release_controls_remain_mandatory():
    data = list(_fixture())
    data[3][0]["source_sha256"] = "f" * 64
    with pytest.raises(ValueError):
        _audit(tuple(data), [_scenario(data)])
    data = list(_fixture())
    data[4] = data[0]["holdout_end_at_utc"] - 1
    with pytest.raises(ValueError):
        _audit(tuple(data), [_scenario(data)])
