"""Synthetic and already-declared aggregate-only unknown-exit sensitivity tests."""
import copy
import json
from decimal import Decimal
from pathlib import Path

import pytest

from app.offline_sweep_aggregate_censor_tipping import _tipping, audit_censored_tipping

FIXTURE = (Path(__file__).resolve().parents[2] / "docs" /
           "offline-sweep-32-archive-confluence-aggregate-20261027.json")


def sample():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_aggregate_tipping_at_5bps_requires_large_positive_unknown_net_outcomes():
    report = audit_censored_tipping(sample())
    row = report["overall_by_extra_bps"]["5"]
    assert row["status"] == "UNKNOWN_EXIT_TIPPING_POINT_ONLY"
    assert Decimal(row["required_unknown_mean_net_r"]) > Decimal("2.57")
    assert Decimal(row["required_unknown_mean_net_r"]) < Decimal("2.58")
    assert Decimal(row["required_unknown_mean_net_r_min"]) <= Decimal(row["required_unknown_mean_net_r"])
    assert Decimal(row["required_unknown_mean_net_r_max"]) >= Decimal(row["required_unknown_mean_net_r"])
    assert report["unknown_exits_not_imputed"] == 244
    assert report["may_execute_order"] is False
    assert report["verified_profitability"] is False


def test_exact_zero_sum_identity_at_both_cost_scenarios():
    report = audit_censored_tipping(sample())
    payload = sample()
    for bps in ("0", "5"):
        observed_total = sum(Decimal(row["observed_mean_net_r_by_extra_bps"][bps]) * row["observed"]
                             for row in payload["states"] if row["observed"])
        required = -observed_total / 244
        printed = Decimal(report["overall_by_extra_bps"][bps]["required_unknown_mean_net_r"])
        assert abs(observed_total + 244 * printed) <= Decimal("0.000002")


def test_six_trade_positive_cell_has_no_censored_outcomes():
    report = audit_censored_tipping(sample())
    cell = next(row for row in report["states"] if row["state"] == "FVG1_MSS1_DISP1")
    assert cell["observed"] == 6 and cell["unknown_exits"] == 0
    for scenario in cell["by_extra_bps"].values():
        assert scenario["status"] == "NO_UNKNOWN_EXITS"
        assert scenario["required_unknown_mean_net_r"] is None


def test_empty_cells_have_no_invented_thresholds():
    report = audit_censored_tipping(sample())
    for cell in report["states"]:
        if cell["observed"] == 0 and cell["unknown_exits"] == 0:
            assert all(v["required_unknown_mean_net_r"] is None
                       for v in cell["by_extra_bps"].values())


def test_state_order_independent():
    data = sample()
    data["states"].reverse()
    assert audit_censored_tipping(data) == audit_censored_tipping(sample())


@pytest.mark.parametrize("field,value", [
    ("may_execute_order", True),
    ("verified_profitability", True),
    ("independent_holdout", True),
    ("source_status", "AUTHENTICATED"),
])
def test_unsafe_claims_rejected(field, value):
    data = copy.deepcopy(sample())
    data[field] = value
    with pytest.raises(ValueError):
        audit_censored_tipping(data)


def test_corrupt_population_rejected_before_tipping_calculation():
    data = sample()
    data["states"][0]["censored"] += 1
    with pytest.raises(ValueError):
        audit_censored_tipping(data)


@pytest.mark.parametrize("observed,censored,weighted", [
    (1, 3, "-0.00001"),
    (1, 3, "0.00001"),
    (2, 7, "0.00001"),
    (2, 7, "-0.00001"),
    (2043, 244, "-628.43952"),
])
def test_synthetic_tipping_bounds_are_outward_rounded(observed, censored, weighted):
    total = Decimal(weighted)
    result = _tipping(observed, censored, total)
    centre = -total / censored
    uncertainty = Decimal("0.000005") * observed / censored
    lower = Decimal(result["required_unknown_mean_net_r_min"])
    upper = Decimal(result["required_unknown_mean_net_r_max"])
    assert lower <= centre - uncertainty
    assert upper >= centre + uncertainty
    assert upper - lower < 2 * uncertainty + Decimal("0.00000002")
    assert abs(Decimal(result["required_unknown_mean_net_r"]) - centre) <= Decimal("0.000000005")


def test_synthetic_rounding_direction_regressions():
    # Half-even previously rounded this lower endpoint upward, falsely
    # excluding possible values inside the declared five-decimal uncertainty.
    positive = _tipping(1, 3, Decimal("-0.00001"))
    assert positive["required_unknown_mean_net_r_min"] == "0.00000166"
    # Half-even previously rounded this upper endpoint downward.
    negative = _tipping(1, 3, Decimal("0.00001"))
    assert negative["required_unknown_mean_net_r_max"] == "-0.00000166"


def test_no_unknown_exits_still_reports_null_tipping_bounds():
    result = _tipping(5, 0, Decimal("-2"))
    assert result["status"] == "NO_UNKNOWN_EXITS"
    assert result["required_unknown_mean_net_r_min"] is None
    assert result["required_unknown_mean_net_r_max"] is None
