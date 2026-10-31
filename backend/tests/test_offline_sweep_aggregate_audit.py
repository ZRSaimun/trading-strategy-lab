"""Synthetic/declared-only aggregate consistency tests, no market data."""
import copy
import json
from pathlib import Path

import pytest
from app.offline_sweep_aggregate_audit import audit_aggregate


FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_declared_census_reconciles_without_claiming_edge():
    result = audit_aggregate(sample())
    assert result["counts"] == {
        "confirmed": 2327, "entered": 2287, "observed": 2043,
        "censored": 244, "missing_entry": 40, "invalid_geometry": 0}
    assert result["reconstructed_observed_mean_net_r_by_extra_bps"]["5"] == "-0.30760623"
    assert result["reconstructed_observed_mean_net_r_by_extra_bps"]["0"] == "0.00731388"
    assert result["positive_observed_cells_at_5bps"] == [{
        "state": "FVG1_MSS1_DISP1", "observed": 6,
        "mean_net_r_at_5bps": "0.70004", "sparse_under_30": True}]
    assert result["censored_outcomes_not_imputed"] == 244
    assert result["may_execute_order"] is False
    assert result["verified_profitability"] is False
    assert result["independent_holdout_verified"] is False


@pytest.mark.parametrize("mutation", [
    lambda p: p["states"].pop(),
    lambda p: p["states"][1].update(state="FVG0_MSS0_DISP0"),
    lambda p: p["states"][0].update(entered=1414),
    lambda p: p["states"][0].update(censored=171),
    lambda p: p["totals"].update(observed=2044),
    lambda p: p["states"][7]["observed_mean_net_r_by_extra_bps"].update(**{"5":"1.70004"}),
    lambda p: p["states"][0]["observed_mean_net_r_by_extra_bps"].update(**{"5":"0.37529"}),
    lambda p: p["states"][2]["observed_mean_net_r_by_extra_bps"].update(**{"5":"0.00000"}),
    lambda p: p["states"][7].update(observed=True),
    lambda p: p.update(independent_holdout=True),
    lambda p: p.update(may_execute_order=True),
    lambda p: p.update(verified_profitability=True),
    lambda p: p["totals"]["observed_mean_net_r_by_extra_bps"].update(**{"5":"-0.30000"}),
    lambda p: p["states"][0]["observed_mean_net_r_by_extra_bps"].update(**{"0":"NaN"}),
    lambda p: p["states"][0]["observed_mean_net_r_by_extra_bps"].update(**{"0":"0.008660"}),
])
def test_rejects_corrupt_or_overstated_research(mutation):
    p = copy.deepcopy(sample())
    mutation(p)
    with pytest.raises(ValueError):
        audit_aggregate(p)


def test_order_does_not_affect_arithmetic_or_positive_cell():
    p = sample()
    p["states"].reverse()
    assert audit_aggregate(p) == audit_aggregate(sample())


def test_report_is_not_independent_data_or_new_backtest():
    p = sample()
    assert p["source_status"] == "UNAUTHENTICATED"
    assert p["cost_status"] == "ILLUSTRATIVE_EXTRA_BPS_NOT_EXECUTABLE"
    assert p["scope"] == "annual_exploratory_later_16_archives"
