"""Synthetic pre-signal volatility research tests; no market data or fills."""
from copy import deepcopy

import pytest

from app.asof_volatility_regime_audit import (
    audit_asof_volatility_regimes, fingerprint_pre_signal_volatility_evidence,
)
from app.frozen_next_open_intent import fingerprint_next_open_intents

T = 1767600000
SOURCE = dict(instrument="XAUUSD", provider="fixture", venue="fixture",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=3)


def manifest(minutes=(0,), excluded=False):
    return dict(
        protocol="frozen-next-open-intent-v1", source=dict(SOURCE),
        eligible_intents=[
            dict(path_id=f"p{i}", signal_at=T + m * 60,
                 direction="LONG", stop="95", target="105")
            for i, m in enumerate(minutes)
        ],
        excluded_signals=([dict(path_id="excluded", signal_at=T - 60,
                                reason="PRE_SIGNAL_DATA_GAP")] if excluded else []),
    )


def bars(signal_at=T, baseline="2", recent="2"):
    result = []
    for i in range(30):
        width = baseline if i <= 15 else recent
        half = str(float(width) / 2)
        result.append(dict(at=signal_at - (29 - i) * 60,
                           open="100", high=str(100 + float(half)),
                           low=str(100 - float(half)), close="100"))
    return result


def evidence(m, widths=None):
    widths = widths or {}
    return dict(protocol="frozen-m1-volatility-evidence-v1",
                source=dict(SOURCE),
                observations=[
                    dict(path_id=x["path_id"],
                         bars=bars(x["signal_at"], *widths.get(x["path_id"], ("2", "2"))))
                    for x in m["eligible_intents"]
                ])


def audit(m=None, e=None, **kwargs):
    m = m if m is not None else manifest()
    e = e if e is not None else evidence(m)
    return audit_asof_volatility_regimes(
        m, fingerprint_next_open_intents(m),
        e, fingerprint_pre_signal_volatility_evidence(e), **kwargs)


def test_fixed_normal_regime_and_completed_confirmation_bar():
    r = audit()
    assert r["counts"]["NORMAL"] == 1
    assert r["unknown_regimes"] == 0
    assert r["no_post_signal_candle_used"] is True
    assert r["intent_samples"][0]["baseline_atr14"] == "2.000000"
    assert r["intent_samples"][0]["recent_atr14"] == "2.000000"
    assert r["intent_samples"][0]["recent_to_baseline_ratio"] == "1.000000"
    assert r["may_execute_order"] is False


def test_compression_at_fixed_boundary():
    m = manifest()
    r = audit(m, evidence(m, {"p0": ("2", "1.5")}))
    assert r["counts"]["COMPRESSION"] == 1
    assert r["intent_samples"][0]["recent_to_baseline_ratio"] == "0.750000"


def test_expansion_at_fixed_boundary():
    m = manifest()
    r = audit(m, evidence(m, {"p0": ("2", "3")}))
    assert r["counts"]["EXPANSION"] == 1
    assert r["intent_samples"][0]["recent_to_baseline_ratio"] == "1.500000"


def test_inside_thresholds_remains_normal():
    m = manifest((0, 120, 240))
    e = evidence(m, {"p0": ("2", "1.6"), "p1": ("2", "2.8"),
                     "p2": ("2", "2")})
    r = audit(m, e)
    assert r["counts"]["NORMAL"] == 3


def test_all_population_states_counted_without_filtering():
    m = manifest((0, 120, 240), excluded=True)
    e = evidence(m, {"p0": ("2", "1"), "p1": ("2", "4")})
    e["observations"][2]["bars"] = []
    r = audit(m, e)
    assert r["counts"]["COMPRESSION"] == 1
    assert r["counts"]["EXPANSION"] == 1
    assert r["counts"]["UNKNOWN_INCOMPLETE_CONTEXT"] == 1
    assert r["eligible_intents"] == 3
    assert r["declared_pre_signal_exclusions"] == 1
    assert r["status"] == "INCOMPLETE_PRE_SIGNAL_CONTEXT"
    assert r["may_exclude_signals"] is False


def test_zero_baseline_unknown_not_falsely_expansion():
    m = manifest()
    e = evidence(m)
    for bar in e["observations"][0]["bars"][:16]:
        bar["high"] = "100"
        bar["low"] = "100"
    r = audit(m, e)
    assert r["counts"]["UNKNOWN_ZERO_BASELINE"] == 1
    assert r["intent_samples"][0]["recent_to_baseline_ratio"] is None


def test_zero_recent_range_classified_compression_not_broker_liquidity():
    m = manifest()
    e = evidence(m)
    for bar in e["observations"][0]["bars"][16:]:
        bar["high"] = "100"
        bar["low"] = "100"
    r = audit(m, e)
    assert r["counts"]["COMPRESSION"] == 1
    assert r["executable_spreads_verified"] is False


def test_one_missing_candle_reports_unknown_without_repair():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"].pop(9)
    r = audit(m, e)
    assert r["counts"]["UNKNOWN_INCOMPLETE_CONTEXT"] == 1


def test_interior_gap_reports_unknown_without_repair():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"].pop(12)
    assert audit(m, e)["unknown_regimes"] == 1


def test_future_next_open_is_rejected_even_if_evidence_rehashed():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"][-1]["at"] = T + 60
    with pytest.raises(ValueError, match="Future"):
        audit(m, e)


def test_older_than_window_candle_rejected():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"][0]["at"] -= 60
    with pytest.raises(ValueError, match="out-of-window"):
        audit(m, e)


def test_complete_population_required_even_when_sample_limit_zero():
    m = manifest((0, 120))
    e = evidence(m)
    e["observations"].pop()
    with pytest.raises(ValueError, match="population"):
        audit(m, e, sample_limit=0)


def test_unregistered_observation_rejected():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["path_id"] = "unregistered"
    with pytest.raises(ValueError, match="population"):
        audit(m, e)


def test_duplicate_observation_id_rejected():
    m = manifest((0, 120))
    e = evidence(m)
    e["observations"][1]["path_id"] = "p0"
    with pytest.raises(ValueError, match="duplicate"):
        fingerprint_pre_signal_volatility_evidence(e)


def test_input_order_independence_and_no_mutation():
    m = manifest((0, 120))
    e = evidence(m)
    original = deepcopy(e)
    r1 = audit(m, e)
    e["observations"].reverse()
    r2 = audit(m, e)
    assert r1 == r2
    assert original["observations"] == list(reversed(e["observations"]))


def test_evidence_tamper_rejected_by_preserved_digest():
    m = manifest()
    e = evidence(m)
    md = fingerprint_next_open_intents(m)
    ed = fingerprint_pre_signal_volatility_evidence(e)
    e["observations"][0]["bars"][0]["high"] = "103"
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        audit_asof_volatility_regimes(m, md, e, ed)


def test_manifest_tamper_rejected_by_preserved_digest():
    m = manifest()
    e = evidence(m)
    md = fingerprint_next_open_intents(m)
    ed = fingerprint_pre_signal_volatility_evidence(e)
    m["eligible_intents"][0]["target"] = "110"
    with pytest.raises(ValueError, match="fingerprint mismatch"):
        audit_asof_volatility_regimes(m, md, e, ed)


def test_source_mismatch_rejected():
    m = manifest()
    e = evidence(m)
    e["source"]["archive_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="source mismatch"):
        audit(m, e)


@pytest.mark.parametrize("value", ["NaN", "-1", "0", "1e3", "1.0000000000001"])
def test_invalid_prices_fail_closed(value):
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"][0]["open"] = value
    with pytest.raises(ValueError, match="decimal|Nonpositive"):
        audit(m, e)


def test_invalid_ohlc_envelope_rejected():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"][0]["low"] = "101"
    with pytest.raises(ValueError, match="OHLC"):
        audit(m, e)


@pytest.mark.parametrize("bad", [True, T + 1, -60])
def test_invalid_clocks_rejected(bad):
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"][0]["at"] = bad
    with pytest.raises(ValueError, match="timestamp"):
        audit(m, e)


def test_duplicate_and_backward_clocks_rejected():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"][2]["at"] = e["observations"][0]["bars"][1]["at"]
    with pytest.raises(ValueError, match="timestamp"):
        audit(m, e)


def test_unknown_evidence_field_rejected():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["future_return"] = "20"
    with pytest.raises(ValueError, match="exactly"):
        audit(m, e)


@pytest.mark.parametrize("limit", [-1, 51, True, 1.0])
def test_invalid_sample_limit_rejected(limit):
    with pytest.raises(ValueError, match="sample limit"):
        audit(sample_limit=limit)


def test_zero_samples_still_counts_every_signal():
    m = manifest((0, 120))
    r = audit(m, sample_limit=0)
    assert r["intent_samples"] == []
    assert r["counts"]["NORMAL"] == 2


def test_evidence_with_more_than_30_bars_rejected():
    m = manifest()
    e = evidence(m)
    e["observations"][0]["bars"].insert(0, dict(e["observations"][0]["bars"][0]))
    with pytest.raises(ValueError, match="At most 30"):
        audit(m, e)
