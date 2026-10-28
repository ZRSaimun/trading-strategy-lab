"""Synthetic/declared-only attrition and illustrative cost-drag regressions."""
import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.offline_sweep_aggregate_attrition import (
    _interval, _percentage, audit_attrition_cost_drag, main,
)

FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_declared_all_state_population_and_cost_drag():
    result = audit_attrition_cost_drag(sample())
    assert result["counts"]["observed"] == 2043
    assert result["counts"]["censored"] == 244
    assert len(result["by_state"]) == 8
    overall = result["overall"]
    assert overall["observed_percent_of_entered_approx"] == "89.3310"
    assert overall["unknown_exit_percent_of_entered_approx"] == "10.6690"
    assert overall["missing_entry_percent_of_confirmed_approx"] == "1.7190"
    sums = overall["observed_net_r_sum_by_extra_bps_rounded_mean_enclosure"]
    assert sums["0"]["central"] == "14.94225000"
    assert sums["5"]["central"] == "-628.43952000"
    drag = overall["observed_net_r_cost_drag_0_to_5_bps_enclosure"]
    assert drag["central"] == "643.38177000"
    assert D(drag["min"]) < D(drag["central"]) < D(drag["max"])
    assert result["unknown_exits_not_imputed"] == 244
    assert result["may_execute_order"] is False
    assert result["verified_profitability"] is False
    assert result["independent_holdout_verified"] is False
    assert result["executable_broker_costs_verified"] is False


def test_sparse_positive_cell_is_not_selected_or_misrepresented():
    rows = {r["state"]: r for r in audit_attrition_cost_drag(sample())["by_state"]}
    rare = rows["FVG1_MSS1_DISP1"]
    assert rare["observed"] == 6
    assert rare["unknown_exits"] == 0
    assert rare["observed_percent_of_all_observed_approx"] == "0.2937"
    assert rare["observed_net_r_sum_by_extra_bps_rounded_mean_enclosure"]["5"]["central"] == "4.20024000"
    assert rows["FVG0_MSS1_DISP0"]["observed_net_r_cost_drag_0_to_5_bps_enclosure"] is None
    assert rows["FVG1_MSS1_DISP0"]["observed_percent_of_entered_approx"] is None
    assert rows["FVG1_MSS1_DISP0"]["unknown_exit_percent_of_entered_approx"] is None


def test_outward_rounding_never_narrows_interval():
    result = _interval(D("1.000000001"), D("0.000000004"))
    assert D(result["min"]) <= D("0.999999997")
    assert D(result["max"]) >= D("1.000000005")
    negative = _interval(D("-1.000000001"), D("0.000000004"))
    assert D(negative["min"]) <= D("-1.000000005")
    assert D(negative["max"]) >= D("-0.999999997")


def test_percentage_null_for_zero_denominator_and_exact_for_nonzero():
    assert _percentage(0, 0) is None
    assert _percentage(0, 10) == "0.0000"
    assert _percentage(1, 8) == "12.5000"


def test_order_independence_and_input_immutability():
    original = sample()
    reversed_input = copy.deepcopy(original)
    reversed_input["states"].reverse()
    assert audit_attrition_cost_drag(original) == audit_attrition_cost_drag(reversed_input)
    assert original == sample()


@pytest.mark.parametrize("mutate", [
    lambda p: p["states"][0].update(observed=1244),
    lambda p: p["states"][0].update(censored=173),
    lambda p: p.update(verified_profitability=True),
    lambda p: p.update(may_execute_order=True),
    lambda p: p["states"][0]["observed_mean_net_r_by_extra_bps"].update(**{"5": "0.37529"}),
])
def test_invalid_aggregate_rejected_before_descriptive_statistics(mutate):
    payload = sample()
    mutate(payload)
    with pytest.raises(ValueError):
        audit_attrition_cost_drag(payload)


def test_cli_declared_fixture_is_read_only_and_safe(capsys):
    before = FIXTURE.read_bytes()
    main([str(FIXTURE)])
    result = json.loads(capsys.readouterr().out)
    assert result["audit"] == "DECLARED_ROUNDED_AGGREGATE_ATTRITION_COST_DRAG_ONLY"
    assert result["may_execute_order"] is False
    assert result["unknown_exits_not_imputed"] == 244
    assert FIXTURE.read_bytes() == before
