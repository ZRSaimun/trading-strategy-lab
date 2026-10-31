"""Synthetic offline five-block omission tests, never live market performance."""
from copy import deepcopy
import math
import pytest
from app.forecast_block_regret_sensitivity import audit_block_regret_sensitivity


def test_five_equal_contiguous_blocks_and_exact_omission_extrema():
    values = [(x / 100, x / 10) for x in (-20, -10, 0, 10, 20) for _ in range(30)]
    before = deepcopy(values)
    r = audit_block_regret_sensitivity(values)
    assert values == before
    assert r["status"] == "DESCRIPTIVE_ONLY"
    assert [(v["startIndex"], v["endIndex"]) for v in r["omittedBlockRanges"]] == [
        (0, 29), (30, 59), (60, 89), (90, 119), (120, 149)]
    expected_brier = [sum(v[0] for v in values[:i*30] + values[(i+1)*30:]) / 120 for i in range(5)]
    expected_log = [sum(v[1] for v in values[:i*30] + values[(i+1)*30:]) / 120 for i in range(5)]
    assert r["retainedMeanBrierRegretBestCase"] == pytest.approx(min(expected_brier))
    assert r["retainedMeanBrierRegretWorstCase"] == pytest.approx(max(expected_brier))
    assert r["retainedMeanLogLossRegretBestCase"] == pytest.approx(min(expected_log))
    assert r["retainedMeanLogLossRegretWorstCase"] == pytest.approx(max(expected_log))
    assert not any(r[k] for k in ("maySendNotification", "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_unequal_blocks_are_fixed_by_index_and_exhaust_population():
    r = audit_block_regret_sensitivity([(0.1, -0.2)] * 153)
    assert [b["omittedCount"] for b in r["omittedBlockRanges"]] == [31, 31, 31, 30, 30]
    assert r["omittedBlockRanges"][-1]["endIndex"] == 152
    assert all(b["retainedCount"] + b["omittedCount"] == 153 for b in r["omittedBlockRanges"])
    assert r["retainedMeanBrierRegretWorstCase"] == pytest.approx(.1)
    assert r["retainedMeanLogLossRegretBestCase"] == pytest.approx(-.2)


def test_one_bad_regime_changes_omission_sensitivity():
    values = [(0.8, 8)] * 30 + [(-0.1, -1)] * 120
    r = audit_block_regret_sensitivity(values)
    assert r["retainedMeanBrierRegretBestCase"] == pytest.approx(-.1)
    assert r["retainedMeanBrierRegretWorstCase"] > 0
    assert r["retainedMeanLogLossRegretBestCase"] == pytest.approx(-1)
    assert r["retainedMeanLogLossRegretWorstCase"] > 0


def test_all_negative_is_not_permission_to_trade():
    r = audit_block_regret_sensitivity([(-.3, -1)] * 150)
    assert r["retainedMeanBrierRegretWorstCase"] < 0
    assert r["retainedMeanLogLossRegretWorstCase"] < 0
    assert not r["sourceAuthenticated"]
    assert not r["independentHoldoutVerified"]
    assert not r["mayExecuteLiveOrder"]


def test_insufficient_population_withholds_every_metric():
    r = audit_block_regret_sensitivity([(0.1, 0.1)] * 149)
    assert r["status"] == "INSUFFICIENT_CONTIGUOUS_BLOCK_SUPPORT"
    assert r["omittedBlockRanges"] is None
    assert r["retainedMeanBrierRegretBestCase"] is None
    assert r["retainedMeanLogLossRegretWorstCase"] is None


@pytest.mark.parametrize("bad,threshold", [
    ([(True, .1)] * 150, 30),
    ([(.1, float('nan'))] * 150, 30),
    ([(float('inf'), .1)] * 150, 30),
    ([(1.1, .1)] * 150, 30),
    ([(.1, 1001)] * 150, 30),
    ([(.1,)] * 150, 30),
    (["bad"] * 150, 30),
    ([(.1, .1)] * 150, True),
    ([(.1, .1)] * 150, 29),
    ([(.1, .1)] * 150, 5001),
    ([(.1, .1)] * 150, 30.0),
    ([(.1, .1)] * 150, -1),
])
def test_invalid_values_fail_closed(bad, threshold):
    with pytest.raises(ValueError):
        audit_block_regret_sensitivity(bad, min_per_block=threshold)


def test_empty_and_unsupported_input_shape_rejected_or_withheld():
    assert audit_block_regret_sensitivity([])["status"] == "INSUFFICIENT_CONTIGUOUS_BLOCK_SUPPORT"
    for bad in ({}, None, 'hello'):
        with pytest.raises(ValueError):
            audit_block_regret_sensitivity(bad)


def test_threshold_controls_sample_gate_without_changing_block_count():
    r = audit_block_regret_sensitivity([(0.1, 0.1)] * 200, min_per_block=40)
    assert r["status"] == "DESCRIPTIVE_ONLY"
    assert len(r["omittedBlockRanges"]) == 5
    assert audit_block_regret_sensitivity([(0.1, 0.1)] * 199, min_per_block=40)["status"] == "INSUFFICIENT_CONTIGUOUS_BLOCK_SUPPORT"


def test_randomized_omissions_match_direct_brute_force():
    import random
    rng = random.Random(20261029)
    for n in (150, 151, 157, 205, 999):
        data = [(rng.uniform(-1, 1), rng.uniform(-10, 10)) for _ in range(n)]
        r = audit_block_regret_sensitivity(data)
        brier, log = [], []
        for block in r["omittedBlockRanges"]:
            keep = [x for i, x in enumerate(data) if not block["startIndex"] <= i <= block["endIndex"]]
            brier.append(math.fsum(x[0] for x in keep) / len(keep))
            log.append(math.fsum(x[1] for x in keep) / len(keep))
        assert r["retainedMeanBrierRegretBestCase"] == pytest.approx(min(brier))
        assert r["retainedMeanBrierRegretWorstCase"] == pytest.approx(max(brier))
        assert r["retainedMeanLogLossRegretBestCase"] == pytest.approx(min(log))
        assert r["retainedMeanLogLossRegretWorstCase"] == pytest.approx(max(log))
