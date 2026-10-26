"""Synthetic-only pseudo-settlement drawdown regression tests."""
from copy import deepcopy
from decimal import Decimal

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_capacity_drawdown import _maximum_drawdown, audit_frozen_capacity_drawdown
from test_frozen_capacity_week_fragility import CUTOFF, sample, move


def run(manifest, paths, **kwargs):
    return audit_frozen_capacity_drawdown(
        manifest, paths, kwargs.pop("digest", fingerprint_population_manifest(manifest)),
        kwargs.pop("cutoff", CUTOFF), kwargs.pop("embargo", 1440), **kwargs,
    )


def test_exact_drawdown_includes_initial_zero_peak():
    assert _maximum_drawdown([Decimal("-1"), Decimal("-2"), Decimal("3")]) == 3
    assert _maximum_drawdown([Decimal("2"), Decimal("-3"), Decimal("-1")]) == 4
    assert _maximum_drawdown([Decimal("1"), Decimal("2")]) == 0


def test_complete_frozen_cohorts_and_losses():
    m, p = sample()
    r = run(m, p)
    assert r["status"] == "DESCRIPTIVE_FIXED_HORIZON_DRAWDOWN_ENVELOPE_ONLY"
    assert r["eligible_signals"] == 72
    assert r["admission_counts"]["holdout_admitted"] == 36
    s = r["cost_scenarios"][0]
    assert Decimal(s["training_pseudo_settlement_maximum_max_drawdown_pct_initial"]) == 0
    assert Decimal(s["holdout_pseudo_settlement_minimum_max_drawdown_pct_initial"]) == 18
    assert Decimal(s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"]) == 18
    assert Decimal(s["holdout_pseudo_settlement_final_lower_pct_initial"]) == -18
    assert r["verified_profitability"] is False
    assert r["may_execute_order"] is False


def test_all_cost_scenarios_and_worsening_drawdown():
    m, p = sample()
    r = run(m, p)
    assert [s["additional_round_trip_bps"] for s in r["cost_scenarios"]] == [0, 5, 10, 20]
    d = [Decimal(s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"])
         for s in r["cost_scenarios"]]
    assert d == sorted(d)


def test_ambiguous_path_keeps_nonzero_envelope():
    m, p = sample()
    p[40]["bars"][0].update(high="103", low="98", close="100")
    s = run(m, p)["cost_scenarios"][0]
    assert Decimal(s["holdout_pseudo_settlement_minimum_max_drawdown_pct_initial"]) < Decimal(
        s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"])


def test_capacity_rejection_is_counted_not_selected_by_winner():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    r = run(m, p)
    assert r["admission_counts"]["holdout_admitted"] == 35
    assert r["admission_counts"]["holdout_unadmitted"] == 1
    assert r["cost_scenarios"][0]["holdout_pseudo_settlement_final_lower_pct_initial"] == "-17.5"


def test_early_target_does_not_release_capacity():
    m, p = sample()
    move(m, p, 37, CUTOFF + 60)
    p[36]["bars"][0].update(high="103", close="100")
    assert run(m, p)["admission_counts"]["holdout_unadmitted"] == 1


def test_input_order_does_not_change_results_or_mutate_data():
    m, p = sample()
    original = deepcopy((m, p))
    expected = run(m, p)
    assert (m, p) == original
    m["eligible_signals"].reverse()
    p.reverse()
    assert run(m, p) == expected


def test_incomplete_path_withholds_all_drawdown_statistics():
    m, p = sample()
    p[40]["bars"] = []
    r = run(m, p)
    assert r["status"].startswith("WITHHELD")
    assert r["cost_scenarios"] == []


def test_declared_exclusions_withhold():
    m, p = sample()
    m["excluded_signals"].append(dict(path_id="excluded", signal_at=CUTOFF - 37 * 7 * 86400,
                                      reason="PRE_SIGNAL_DATA_GAP"))
    assert run(m, p)["cost_scenarios"] == []


def test_insufficient_admitted_holdout_withholds():
    m, p = sample()
    for i in range(37, 49):
        move(m, p, i, CUTOFF + (i - 36) * 60)
    assert run(m, p)["cost_scenarios"] == []


def test_invalid_digest_fails_closed():
    m, p = sample()
    with pytest.raises(ValueError, match="SHA-256"):
        run(m, p, digest="f" * 64)


def test_bad_policy_and_cutoff_fail_closed():
    m, p = sample()
    with pytest.raises(ValueError):
        run(m, p, max_positions=0)
    with pytest.raises(ValueError):
        run(m, p, cutoff=CUTOFF + 60)
    with pytest.raises(ValueError):
        run(m, p, embargo=0)


def test_risk_bps_scale_pseudo_equity_not_broker_margin():
    m, p = sample()
    s = run(m, p, per_position_risk_bps=50)["cost_scenarios"][0]
    assert Decimal(s["holdout_pseudo_settlement_maximum_max_drawdown_pct_initial"]) == 9
