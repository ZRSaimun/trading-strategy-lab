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
        "additional_cost_share_of_positive_baseline_net_bps": 370,
        "positive_baseline_net_erased_by_stress": False,
        "max_single_observation_extra_cost_cash": "1.2500",
        "additional_cost_affected_observation_count": 2,
        "max_single_observation_extra_cost_share_bps": 6250,
        "worst_observation_stressed_net_cash": "0.6500",
        "max_observation_end_drawdown_cash": "0.0000",
        "max_receipt_time_ordering_drawdown_cash_upper_bound": "0.0000",
        "baseline_losing_observation_count": 0,
        "stressed_losing_observation_count": 0,
        "additional_cost_induced_losing_observation_count": 0,
        "additional_cost_erased_positive_observation_count": 0,
        "positive_observation_cash_eroded_by_stress": "2.0000",
        "stressed_gross_loss_cash": "0.0000",
        "additional_cost_induced_gross_loss_cash": "0.0000",
        "max_single_stressed_loss_share_bps": None,
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
    assert result["scenarios"][0]["additional_cost_affected_observation_count"] == 0
    assert result["scenarios"][0]["max_single_observation_extra_cost_share_bps"] is None
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
    assert entry["additional_cost_share_of_positive_baseline_net_bps"] is None
    assert entry["positive_baseline_net_erased_by_stress"] is None
    assert entry["max_single_observation_extra_cost_cash"] is None
    assert entry["additional_cost_affected_observation_count"] is None
    assert entry["max_single_observation_extra_cost_share_bps"] is None
    assert entry["worst_observation_stressed_net_cash"] is None
    assert entry["max_observation_end_drawdown_cash"] is None
    assert entry["max_receipt_time_ordering_drawdown_cash_upper_bound"] is None
    assert entry["baseline_losing_observation_count"] is None
    assert entry["stressed_losing_observation_count"] is None
    assert entry["additional_cost_induced_losing_observation_count"] is None
    assert entry["additional_cost_erased_positive_observation_count"] is None
    assert entry["positive_observation_cash_eroded_by_stress"] is None
    assert entry["stressed_gross_loss_cash"] is None
    assert entry["additional_cost_induced_gross_loss_cash"] is None
    assert entry["max_single_stressed_loss_share_bps"] is None
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


def test_stressed_receipt_drawdown_and_worst_row_are_exact():
    data = _fixture()
    stress = _scenario(data, per_row={0: {"spread_extra_cash": "5.0000"}})
    entry = _audit(data, [stress])["scenarios"][0]
    assert entry["stressed_net_cash"] == "49.0000"
    assert entry["worst_observation_stressed_net_cash"] == "-3.1000"
    assert entry["max_observation_end_drawdown_cash"] == "3.1000"
    assert entry["max_receipt_time_ordering_drawdown_cash_upper_bound"] == "3.1000"


def test_same_second_receipts_report_ordering_ambiguity():
    data = _fixture()
    # Every label is available before this declared common receipt time.
    for outcome in data[3]:
        outcome["observed_at_utc"] = data[4]
    stress = _scenario(data, per_row={0: {"spread_extra_cash": "5.0000"}})
    entry = _audit(data, [stress])["scenarios"][0]
    assert entry["stressed_net_cash"] == "49.0000"
    assert entry["max_observation_end_drawdown_cash"] == "0.0000"
    assert entry["max_receipt_time_ordering_drawdown_cash_upper_bound"] == "3.1000"
    assert entry["worst_observation_stressed_net_cash"] == "-3.1000"
    reordered = copy.deepcopy(data)
    reordered[3].reverse()
    stress["adjustments"].reverse()
    assert _audit(reordered, [stress])["scenarios"][0] == entry


def test_cost_position_changes_receipt_drawdown_not_total():
    data = _fixture()
    early = _scenario(data, "early", {0: {"spread_extra_cash": "5.0000"}})
    late = _scenario(data, "late", {1: {"spread_extra_cash": "5.0000"}})
    reports = {r["scenario_id"]: r for r in _audit(data, [early, late])["scenarios"]}
    assert reports["early"]["stressed_net_cash"] == reports["late"]["stressed_net_cash"]
    assert reports["early"]["max_observation_end_drawdown_cash"] == "3.1000"
    assert reports["late"]["max_observation_end_drawdown_cash"] == "3.3000"
    assert reports["late"]["worst_observation_stressed_net_cash"] == "-3.3000"


def test_stressed_cash_diagnostics_do_not_grant_execution_permission():
    data = _fixture()
    report = _audit(data, [_scenario(data)])
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False
    assert report["holdout_untouched_independently_verified"] is False
    assert report["broker_costs_verified"] is False
    assert report["scenarios"][0]["max_observation_end_drawdown_cash"] == "0.0000"


def test_adverse_costs_create_a_new_losing_observation():
    data = _fixture()
    scenario = _scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
    })
    report = _audit(data, [scenario])["scenarios"][0]
    assert report["baseline_losing_observation_count"] == 0
    assert report["stressed_losing_observation_count"] == 1
    assert report["additional_cost_induced_losing_observation_count"] == 1
    assert report["stressed_gross_loss_cash"] == "3.1000"
    assert report["stressed_net_cash"] == "49.0000"


def test_existing_losing_observation_is_not_cost_induced():
    data = _fixture()
    data[3][0]["gross_cash"] = "-1.0000"
    scenario = _scenario(data, per_row={
        0: {"slippage_extra_cash": "5.0000"},
    })
    report = _audit(data, [scenario])["scenarios"][0]
    assert report["baseline_losing_observation_count"] == 1
    assert report["stressed_losing_observation_count"] == 1
    assert report["additional_cost_induced_losing_observation_count"] == 0
    assert report["stressed_gross_loss_cash"] == "6.1000"


def test_exact_zero_to_negative_counts_as_cost_induced_loss():
    data = _fixture()
    # First receipt: 0.1000 gross - 0.2000 costs + 0.1000
    # signed financing credit = exact zero before additional cost.
    data[3][0]["gross_cash"] = "0.1000"
    scenario = _scenario(data, per_row={
        0: {"fx_extra_cash": "0.0001"},
    })
    report = _audit(data, [scenario])["scenarios"][0]
    assert report["baseline_losing_observation_count"] == 0
    assert report["stressed_losing_observation_count"] == 1
    assert report["additional_cost_induced_losing_observation_count"] == 1
    assert report["stressed_gross_loss_cash"] == "0.0001"


def test_more_adverse_costs_cannot_reduce_losing_population():
    data = _fixture()
    mild = _scenario(data, "mild", {
        0: {"commission_extra_cash": "1.8999"},
    })
    severe = _scenario(data, "severe", {
        0: {"commission_extra_cash": "1.9001"},
        1: {"financing_extra_cash": "2.0000"},
    })
    reports = {
        row["scenario_id"]: row
        for row in _audit(data, [severe, mild])["scenarios"]
    }
    assert reports["mild"]["stressed_losing_observation_count"] == 0
    assert reports["severe"]["stressed_losing_observation_count"] == 2
    assert reports["severe"]["additional_cost_induced_losing_observation_count"] == 2
    assert Decimal(reports["severe"]["stressed_gross_loss_cash"]) > 0
    assert reports["severe"]["stressed_net_cash"] < reports["mild"]["stressed_net_cash"]


def test_single_row_carries_all_additional_cost_and_reports_full_concentration():
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"financing_extra_cash": "4.0000"},
    })])["scenarios"][0]
    assert report["extra_cost_cash"] == "4.0000"
    assert report["additional_cost_affected_observation_count"] == 1
    assert report["max_single_observation_extra_cost_share_bps"] == 10000


def test_equal_row_costs_have_half_share_and_two_affected_observations():
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "0.5000"},
        1: {"slippage_extra_cash": "0.5000"},
    })])["scenarios"][0]
    assert report["additional_cost_affected_observation_count"] == 2
    assert report["max_single_observation_extra_cost_share_bps"] == 5000


def test_largest_row_share_uses_conservative_integer_floor_without_float():
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "1.0000"},
        1: {"slippage_extra_cash": "1.0000"},
        2: {"commission_extra_cash": "1.0000"},
    })])["scenarios"][0]
    assert report["additional_cost_affected_observation_count"] == 3
    assert report["max_single_observation_extra_cost_share_bps"] == 3333
    assert report["extra_cost_cash"] == "3.0000"


def test_tiny_exact_cash_cost_concentration_and_execution_disabled():
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"fx_extra_cash": "0.0001"},
        1: {"financing_extra_cash": "0.0002"},
    })])
    entry = report["scenarios"][0]
    assert entry["additional_cost_affected_observation_count"] == 2
    assert entry["max_single_observation_extra_cost_share_bps"] == 6666
    assert report["may_execute_demo_order"] is False
    assert report["may_execute_real_order"] is False


def test_cost_induced_gross_loss_and_single_loss_share_are_exact():
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert report["stressed_gross_loss_cash"] == "3.1000"
    assert report["additional_cost_induced_gross_loss_cash"] == "3.1000"
    assert report["max_single_stressed_loss_share_bps"] == 10000


def test_preexisting_loss_is_not_cost_induced_gross_loss():
    data = _fixture()
    data[3][0]["gross_cash"] = "-1.0000"
    report = _audit(data, [_scenario(data, per_row={
        0: {"slippage_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert report["stressed_gross_loss_cash"] == "6.1000"
    assert report["additional_cost_induced_gross_loss_cash"] == "0.0000"
    assert report["max_single_stressed_loss_share_bps"] == 10000


def test_two_stressed_losses_use_floor_rounded_largest_share():
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
        1: {"financing_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert report["stressed_losing_observation_count"] == 2
    assert report["stressed_gross_loss_cash"] == "6.4000"
    assert report["additional_cost_induced_gross_loss_cash"] == "6.4000"
    assert report["max_single_stressed_loss_share_bps"] == 5156


def test_no_stressed_losses_have_undefined_loss_concentration():
    data = _fixture()
    report = _audit(data, [_scenario(data)])["scenarios"][0]
    assert report["stressed_gross_loss_cash"] == "0.0000"
    assert report["additional_cost_induced_gross_loss_cash"] == "0.0000"
    assert report["max_single_stressed_loss_share_bps"] is None


def test_cost_induced_loss_metrics_do_not_release_small_holdout():
    data = _fixture(29)
    report = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
    })])
    assert report["scenarios"][0]["additional_cost_induced_gross_loss_cash"] is None
    assert report["scenarios"][0]["max_single_stressed_loss_share_bps"] is None
    assert report["may_execute_real_order"] is False


@pytest.mark.parametrize(("extra", "expected_bps", "erased"), [
    ("27.0000", 5000, False),
    ("54.0000", 10000, True),
    ("54.0001", 10000, True),
])
def test_positive_declared_net_cost_erosion_boundary(extra, expected_bps, erased):
    data = _fixture()
    report = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": extra},
    })])
    entry = report["scenarios"][0]
    assert entry["additional_cost_share_of_positive_baseline_net_bps"] == expected_bps
    assert entry["positive_baseline_net_erased_by_stress"] is erased
    assert Decimal(entry["stressed_net_cash"]) == Decimal("54.0000") - Decimal(extra)
    assert report["may_execute_real_order"] is False


@pytest.mark.parametrize("gross", ["-52.0000", "-52.0001"])
def test_zero_or_negative_baseline_does_not_report_positive_net_erosion(gross):
    data = _fixture()
    data[3][0]["gross_cash"] = gross
    entry = _audit(data, [_scenario(data, per_row={
        0: {"slippage_extra_cash": "0.0001"},
    })])["scenarios"][0]
    assert entry["additional_cost_share_of_positive_baseline_net_bps"] is None
    assert entry["positive_baseline_net_erased_by_stress"] is False


def test_signed_financing_credit_affects_positive_net_erosion_denominator():
    data = _fixture()
    for row in data[3]:
        row["financing_cash"] = "-0.1000"
    report = _audit(data, [_scenario(data, per_row={
        0: {"financing_extra_cash": "28.5000"},
    })])
    assert report["baseline_net_cash"] == "57.0000"
    entry = report["scenarios"][0]
    assert entry["additional_cost_share_of_positive_baseline_net_bps"] == 5000
    assert entry["positive_baseline_net_erased_by_stress"] is False
    assert report["may_execute_demo_order"] is False


def test_adverse_cost_erases_positive_row_without_double_counting_overshoot():
    data = _fixture()
    entry = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert entry["additional_cost_erased_positive_observation_count"] == 1
    assert entry["positive_observation_cash_eroded_by_stress"] == "1.9000"
    assert entry["additional_cost_induced_gross_loss_cash"] == "3.1000"


@pytest.mark.parametrize(("extra", "erased"), [
    ("1.8999", 0),
    ("1.9000", 1),
    ("1.9001", 1),
])
def test_positive_row_erasure_includes_exact_zero_boundary(extra, erased):
    data = _fixture()
    entry = _audit(data, [_scenario(data, per_row={
        0: {"slippage_extra_cash": extra},
    })])["scenarios"][0]
    assert entry["additional_cost_erased_positive_observation_count"] == erased
    assert entry["positive_observation_cash_eroded_by_stress"] == format(
        min(Decimal(extra), Decimal("1.9000")), ".4f"
    )


def test_preexisting_losing_row_does_not_count_as_erased_positive():
    data = _fixture()
    data[3][0]["gross_cash"] = "-1.0000"
    entry = _audit(data, [_scenario(data, per_row={
        0: {"commission_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert entry["additional_cost_erased_positive_observation_count"] == 0
    assert entry["positive_observation_cash_eroded_by_stress"] == "0.0000"
    assert entry["stressed_losing_observation_count"] == 1


def test_two_erased_positive_rows_have_capped_additive_cash_erosion():
    data = _fixture()
    entry = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
        1: {"financing_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert entry["additional_cost_erased_positive_observation_count"] == 2
    assert entry["positive_observation_cash_eroded_by_stress"] == "3.6000"
    assert entry["stressed_gross_loss_cash"] == "6.4000"


def test_erased_positive_cash_uses_signed_baseline_financing():
    data = _fixture()
    data[3][0]["financing_cash"] = "-0.2000"
    entry = _audit(data, [_scenario(data, per_row={
        0: {"fx_extra_cash": "2.0000"},
    })])["scenarios"][0]
    assert entry["additional_cost_erased_positive_observation_count"] == 1
    assert entry["positive_observation_cash_eroded_by_stress"] == "2.0000"


def test_erased_positive_metrics_withheld_below_thirty():
    data = _fixture(29)
    entry = _audit(data, [_scenario(data, per_row={
        0: {"spread_extra_cash": "5.0000"},
    })])["scenarios"][0]
    assert entry["additional_cost_erased_positive_observation_count"] is None
    assert entry["positive_observation_cash_eroded_by_stress"] is None
