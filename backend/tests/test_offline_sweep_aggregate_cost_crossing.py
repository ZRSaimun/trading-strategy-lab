"""Synthetic and declared aggregate tests; no private market observations."""
import copy
import json
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.offline_sweep_aggregate_cost_crossing import _crossing, audit_cost_crossing

FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_declared_overall_observed_only_crossing_and_safety_flags():
    result = audit_cost_crossing(sample())
    overall = result["overall"]
    assert overall["observed"] == 2043
    assert overall["censored"] == 244
    assert overall["status"] == "ROUNDED_OBSERVED_ONLY_INTERPOLATED_CROSSING"
    assert overall["zero_crossing_extra_bps"] == "0.11612273"
    assert D(overall["lower_bound_extra_bps"]) < D("0.11612273")
    assert D(overall["upper_bound_extra_bps"]) > D("0.11612273")
    assert result["unknown_exits_not_imputed"] == 244
    assert result["verified_profitability"] is False
    assert result["may_execute_order"] is False
    assert result["independent_holdout_verified"] is False
    assert result["executable_broker_costs_verified"] is False


def test_eight_states_preserved_without_retrospective_selection():
    result = audit_cost_crossing(sample())
    assert len(result["by_state"]) == 8
    by_name = {row["state"]: row for row in result["by_state"]}
    assert by_name["FVG0_MSS1_DISP0"]["status"] == "NO_OBSERVED_EXITS"
    assert by_name["FVG1_MSS1_DISP0"]["status"] == "NO_OBSERVED_EXITS"
    assert by_name["FVG1_MSS1_DISP1"]["observed"] == 6
    assert by_name["FVG1_MSS1_DISP1"]["status"] == "NO_STRICT_CROSSING_WITHIN_DECLARED_0_TO_5_BPS"
    assert by_name["FVG1_MSS1_DISP1"]["zero_crossing_extra_bps"] is None
    assert by_name["FVG0_MSS0_DISP1"]["status"] == "NOT_STRICTLY_POSITIVE_AT_ZERO_BPS"
    assert by_name["FVG0_MSS1_DISP1"]["status"] == "ROUNDED_OBSERVED_ONLY_INTERPOLATED_CROSSING"


def test_order_independent_and_does_not_mutate_input():
    original = sample()
    reverse = copy.deepcopy(original)
    reverse["states"].reverse()
    assert audit_cost_crossing(reverse) == audit_cost_crossing(original)
    assert original == sample()


@pytest.mark.parametrize("gross,cost5,expected", [
    ("0.10000", "-0.10000", "ROUNDED_OBSERVED_ONLY_INTERPOLATED_CROSSING"),
    ("-0.10000", "-0.20000", "NOT_STRICTLY_POSITIVE_AT_ZERO_BPS"),
    ("0.00000", "-0.10000", "ROUNDING_AMBIGUOUS_ENDPOINT"),
    ("0.10000", "0.05000", "NO_STRICT_CROSSING_WITHIN_DECLARED_0_TO_5_BPS"),
    ("0.10000", "0.00000", "ROUNDING_AMBIGUOUS_ENDPOINT"),
])
def test_synthetic_endpoint_statuses(gross, cost5, expected):
    assert _crossing(D(gross), D(cost5), 1)["status"] == expected


def test_synthetic_crossing_and_rounding_bounds():
    result = _crossing(D("0.10000"), D("-0.10000"), 1)
    assert result["zero_crossing_extra_bps"] == "2.50000000"
    assert D(result["lower_bound_extra_bps"]) < D("2.5")
    assert D(result["upper_bound_extra_bps"]) > D("2.5")
    near = _crossing(D("0.00001"), D("-0.00001"), 1)
    assert D(near["lower_bound_extra_bps"]) < D(near["zero_crossing_extra_bps"])
    assert D(near["zero_crossing_extra_bps"]) < D(near["upper_bound_extra_bps"])


def test_empty_observed_cell_has_no_interpolation():
    result = _crossing(D(0), D(0), 0)
    assert result["status"] == "NO_OBSERVED_EXITS"
    assert result["zero_crossing_extra_bps"] is None


@pytest.mark.parametrize("mutation", [
    lambda p: p.update(independent_holdout=True),
    lambda p: p.update(may_execute_order=True),
    lambda p: p["states"][0].update(observed=1244),
    lambda p: p["states"][0]["observed_mean_net_r_by_extra_bps"].update(**{"5": "0.37529"}),
    lambda p: p["totals"].update(censored=245),
])
def test_rejects_invalid_or_unsafe_aggregate_before_interpolation(mutation):
    p = sample()
    mutation(p)
    with pytest.raises(ValueError):
        audit_cost_crossing(p)


@pytest.mark.parametrize("gross,cost5", [
    ("0.00000", "-0.00001"),
    ("0.00000", "0.00000"),
    ("0.00001", "0.00000"),
    ("0.00001", "-0.00000"),
])
def test_rounded_zero_endpoints_never_claim_strict_crossing(gross, cost5):
    result = _crossing(D(gross), D(cost5), 1)
    assert result["status"] == "ROUNDING_AMBIGUOUS_ENDPOINT"
    assert result["zero_crossing_extra_bps"] is None
    assert result["lower_bound_extra_bps"] is None
    assert result["upper_bound_extra_bps"] is None


def test_one_last_place_signs_still_prove_strict_crossing():
    result = _crossing(D("0.00001"), D("-0.00001"), 1)
    assert result["status"] == "ROUNDED_OBSERVED_ONLY_INTERPOLATED_CROSSING"
    assert D(result["lower_bound_extra_bps"]) > 0
    assert D(result["upper_bound_extra_bps"]) < 5


def test_nonzero_endpoint_classification_still_decisive():
    assert _crossing(D("-0.00001"), D("-0.10000"), 1)["status"] == (
        "NOT_STRICTLY_POSITIVE_AT_ZERO_BPS"
    )
    assert _crossing(D("0.10000"), D("0.00001"), 1)["status"] == (
        "NO_STRICT_CROSSING_WITHIN_DECLARED_0_TO_5_BPS"
    )
