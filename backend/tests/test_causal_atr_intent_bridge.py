"""Synthetic causality tests only; no actual archive, quote or broker evidence."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.causal_atr_intent_bridge import compile_causal_atr_intents
from app.frozen_next_open_intent import audit_next_open_intents

T = int(datetime(2026, 1, 5, 13, 0, tzinfo=timezone.utc).timestamp())
SOURCE = dict(instrument="XAUUSD", provider="fixture", venue="fixture",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def candle(at, o="100", h="101", l="99", c="100"):
    return dict(at=at, open=o, high=h, low=l, close=c)


def candidate(path_id="one", close_at=T, direction="LONG"):
    return dict(path_id=path_id, confirmation_close_at=close_at,
                direction=direction, hypothesis="CRT_ICT_SWEEP_MSS_FVG_CANDIDATE",
                m1_pre_signal=[candle(close_at - 15 * 60 + i * 60) for i in range(15)])


def compile(*signals, source=None):
    return compile_causal_atr_intents(deepcopy(source or SOURCE), deepcopy(list(signals)))


def test_long_bracket_uses_completed_true_ranges_only():
    r = compile(candidate())
    intent = r["manifest"]["eligible_intents"][0]
    assert intent == dict(path_id="one", signal_at=T - 60, direction="LONG",
                          stop="97.000000000000", target="106.000000000000")
    assert r["eligible_count"] == 1
    assert r["excluded_count"] == 0
    assert r["upstream_signal_verified"] is False
    assert r["verified_profitability"] is False
    assert "entry" not in intent


def test_short_bracket_and_next_open_audit_compatibility():
    r = compile(candidate(direction="SHORT"))
    intent = r["manifest"]["eligible_intents"][0]
    assert intent["stop"] == "103.000000000000"
    assert intent["target"] == "94.000000000000"
    result = audit_next_open_intents(
        r["manifest"], [dict(path_id="one", bars=[candle(T)])], r["manifest_sha256"]
    )
    assert result["eligible_intents"] == 1
    assert result["paths"][0]["entry_observed"] == "100"
    assert result["status"] == "INSUFFICIENT_SAMPLE"


def test_future_candle_at_confirmation_close_rejected():
    s = candidate()
    s["m1_pre_signal"][-1]["at"] = T
    with pytest.raises(ValueError, match="future"):
        compile(s)


def test_unobserved_prior_minute_is_declared_exclusion():
    good = candidate()
    bad = candidate("gap", T + 7 * 86400)
    bad["m1_pre_signal"].pop(5)
    r = compile(good, bad)
    assert r["status"] == "PRE_SIGNAL_EXCLUSIONS"
    assert r["eligible_count"] == 1 and r["excluded_count"] == 1
    assert r["manifest"]["excluded_signals"] == [
        dict(path_id="gap", signal_at=bad["confirmation_close_at"] - 60,
             reason="PRE_SIGNAL_DATA_GAP")
    ]
    obs = [dict(path_id="one", bars=[candle(T)])]
    result = audit_next_open_intents(r["manifest"], obs, r["manifest_sha256"])
    assert result["status"] == "UNVERIFIED_EXCLUSIONS"
    assert all(x["population_mean_lower_net_r"] is None for x in result["cost_scenarios"])


def test_missing_first_bar_is_declared_exclusion():
    bad = candidate("gap", T + 7 * 86400)
    bad["m1_pre_signal"].pop(0)
    assert compile(candidate(), bad)["excluded_count"] == 1


def test_earlier_gap_not_repaired_by_stitching():
    bad = candidate("gap", T + 7 * 86400)
    bad["m1_pre_signal"][5]["at"] += 60
    with pytest.raises(ValueError, match="Duplicate"):
        compile(bad)


def test_backward_pre_signal_clock_rejected():
    s = candidate()
    s["m1_pre_signal"][5]["at"] = s["m1_pre_signal"][4]["at"] - 60
    with pytest.raises(ValueError, match="Duplicate"):
        compile(s)


def test_malformed_ohlc_rejected_not_cherry_picked():
    s = candidate()
    s["m1_pre_signal"][0]["low"] = "101"
    with pytest.raises(ValueError, match="OHLC"):
        compile(s)


@pytest.mark.parametrize("value", ["NaN", "1e5", "-100", "0", "100.0000000000001"])
def test_malformed_or_nonpositive_price_rejected(value):
    s = candidate()
    s["m1_pre_signal"][0]["open"] = value
    with pytest.raises(ValueError, match="decimal|Nonpositive"):
        compile(s)


def test_unknown_candidate_field_rejected():
    s = candidate()
    s["future_return"] = "10"
    with pytest.raises(ValueError, match="exactly"):
        compile(s)


def test_duplicate_id_and_confirmation_close_rejected():
    a, b = candidate(), candidate("two", T + 7 * 86400)
    b["path_id"] = a["path_id"]
    with pytest.raises(ValueError, match="Duplicate candidate"):
        compile(a, b)
    b = candidate("two", T)
    with pytest.raises(ValueError, match="Duplicate candidate"):
        compile(a, b)


def test_all_excluded_population_is_not_publishable():
    s = candidate()
    s["m1_pre_signal"] = []
    with pytest.raises(ValueError, match="No eligible"):
        compile(s)


def test_zero_atr_is_declared_exclusion():
    bad = candidate("flat", T + 7 * 86400)
    bad["m1_pre_signal"] = [
        candle(row["at"], "100", "100", "100", "100") for row in bad["m1_pre_signal"]
    ]
    r = compile(candidate(), bad)
    assert r["manifest"]["excluded_signals"][0]["reason"] == "INVALID_PRE_SIGNAL_CONTEXT"


def test_volatility_stop_below_zero_is_declared_exclusion():
    bad = candidate("wide", T + 7 * 86400)
    bad["m1_pre_signal"] = [
        candle(row["at"], "1", "100", "0.1", "1") for row in bad["m1_pre_signal"]
    ]
    r = compile(candidate(), bad)
    assert r["manifest"]["excluded_signals"][0]["reason"] == "INVALID_PRE_SIGNAL_CONTEXT"


def test_evidence_hash_binds_prior_candles_even_when_bracket_unchanged():
    s = candidate()
    baseline = compile(s)
    s["m1_pre_signal"][0]["open"] = "100.1"
    modified = compile(s)
    assert baseline["manifest_sha256"] == modified["manifest_sha256"]
    assert baseline["pre_signal_evidence_sha256"] != modified["pre_signal_evidence_sha256"]


def test_manifest_hash_is_canonical_across_signal_input_order():
    a, b = candidate(), candidate("two", T + 7 * 86400)
    assert compile(a, b)["manifest_sha256"] == compile(b, a)["manifest_sha256"]
    assert compile(a, b)["pre_signal_evidence_sha256"] == compile(b, a)["pre_signal_evidence_sha256"]


def test_source_identity_is_bound_to_both_hashes():
    a = compile(candidate())
    source = dict(SOURCE, provider="other-provider")
    b = compile(candidate(), source=source)
    assert a["manifest_sha256"] != b["manifest_sha256"]
    assert a["pre_signal_evidence_sha256"] != b["pre_signal_evidence_sha256"]


def test_inputs_are_not_mutated():
    source, signals = deepcopy(SOURCE), [candidate()]
    before = deepcopy((source, signals))
    compile_causal_atr_intents(source, signals)
    assert (source, signals) == before


def test_invalid_hypothesis_or_nonminute_confirmation_rejected():
    s = candidate()
    s["hypothesis"] = "UNVERIFIED"
    with pytest.raises(ValueError, match="hypothesis"):
        compile(s)
    s = candidate()
    s["confirmation_close_at"] += 1
    with pytest.raises(ValueError, match="UTC close"):
        compile(s)


def test_input_population_limit():
    with pytest.raises(ValueError, match="bounded"):
        compile_causal_atr_intents(SOURCE, [candidate()] * 10001)
