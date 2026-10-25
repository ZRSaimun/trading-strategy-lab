"""Synthetic tests: software causality, not a historical performance claim."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.causal_m1_confluence_detector import detect_completed_m1_confluence

T = int(datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp())
SOURCE = dict(instrument="XAUUSD", provider="fixture", venue="fixture",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def bar(i, o="100", h="101", l="99", c="100", at=None):
    return dict(at=T + i * 60 if at is None else at, open=o, high=h, low=l, close=c)


def fixture(direction="LONG"):
    bars = [bar(i) for i in range(20)]
    if direction == "LONG":
        bars += [bar(20, l="98"), bar(21, o="102", h="104", l="101.5", c="103.5")]
    else:
        bars += [bar(20, h="102"), bar(21, o="98", h="98.5", l="96", c="96.5")]
    return bars


def detect(bars, source=None, cutoff=None):
    return detect_completed_m1_confluence(deepcopy(source or SOURCE), deepcopy(bars),
                                         cutoff if cutoff is not None else bars[-1]["at"] + 60)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_strict_sweep_mss_fvg_confirmation_is_causal_and_bridge_shaped(direction):
    bars = fixture(direction)
    result = detect(bars)
    assert result["sweep_count"] == 1
    assert result["confirmed_count"] == 1
    assert result["pending_sweeps"] == 0
    candidate = result["candidates"][0]
    assert set(candidate) == {"path_id", "confirmation_close_at", "direction", "hypothesis", "m1_pre_signal"}
    assert candidate["direction"] == direction
    assert candidate["confirmation_close_at"] == T + 22 * 60
    assert candidate["hypothesis"] == "CRT_ICT_SWEEP_MSS_FVG_CANDIDATE"
    assert [x["at"] for x in candidate["m1_pre_signal"]] == [T + i * 60 for i in range(7, 22)]
    assert result["verified_profitability"] is False
    assert result["independently_preregistered"] is False
    assert result["source_authenticated"] is False
    assert all("entry" not in x for x in result["candidates"])


def test_no_confirmation_at_sweep_candle_and_pending_is_explicit():
    result = detect(fixture()[:-1])
    assert result["sweep_count"] == 1
    assert result["confirmed_count"] == 0
    assert result["pending_sweeps"] == 1


def test_no_lookahead_prefix_invariance():
    bars = fixture()
    earlier = detect(bars)
    later = detect(bars + [bar(22), bar(23)])
    assert earlier["candidates"] == later["candidates"]
    assert earlier["snapshot_sha256"] != later["snapshot_sha256"]


def test_missing_fvg_does_not_count_mss_as_confirmation():
    bars = fixture()
    bars[21] = bar(21, o="100", h="104", l="100", c="103.5")
    result = detect(bars)
    assert result["sweep_count"] == 1
    assert result["confirmed_count"] == 0


def test_fvg_without_mss_does_not_confirm():
    bars = fixture()
    bars[21] = bar(21, o="102", h="102.5", l="101.5", c="101.6")
    assert detect(bars)["confirmed_count"] == 0


def test_sweep_not_reclaimed_is_not_a_signal():
    bars = fixture()
    bars[20] = bar(20, o="99", h="101", l="98", c="98.5")
    assert detect(bars)["sweep_count"] == 0
    assert detect(bars)["confirmed_count"] == 0


def test_double_sweep_is_ambiguous_not_directionally_selected():
    bars = fixture()
    bars[20] = bar(20, h="102", l="98")
    result = detect(bars)
    assert result["ambiguous_double_sweeps"] == 1
    assert result["sweep_count"] == 0
    assert result["confirmed_count"] == 0


def test_gap_after_sweep_censors_instead_of_stitching():
    bars = fixture()
    bars[21]["at"] += 60
    result = detect(bars)
    assert result["gap_censored_sweeps"] == 1
    assert result["confirmed_count"] == 0


def test_gap_in_warmup_blocks_sweep():
    bars = fixture()
    bars[10]["at"] += 60
    for k in range(11, len(bars)):
        bars[k]["at"] += 60
    assert detect(bars)["confirmed_count"] == 0


def test_competing_sweeps_fail_closed_not_cherry_picked():
    bars = [bar(i) for i in range(20)]
    bars += [bar(20, l="98"), bar(21, l="97"),
             bar(22, o="102", h="104", l="101.5", c="103.5")]
    with pytest.raises(ValueError, match="Competing sweep"):
        detect(bars)


def test_unconfirmed_full_window_is_expired_not_pending():
    bars = fixture()[:-1] + [bar(i) for i in range(21, 26)]
    result = detect(bars)
    assert result["confirmed_count"] == 0
    assert result["pending_sweeps"] == 0
    assert result["expired_sweeps"] == 1


def test_cutoff_must_equal_last_completed_bar_close():
    bars = fixture()
    with pytest.raises(ValueError, match="Last completed"):
        detect(bars, cutoff=bars[-1]["at"] + 120)
    with pytest.raises(ValueError, match="Noncompleted"):
        detect(bars, cutoff=bars[-1]["at"])


def test_malformed_prices_and_extra_fields_rejected():
    for field, value in (("low", "105"), ("high", "NaN"), ("close", "1e2"), ("open", "0")):
        bars = fixture()
        bars[0][field] = value
        with pytest.raises(ValueError):
            detect(bars)
    bars = fixture()
    bars[0]["future_profit"] = "100"
    with pytest.raises(ValueError, match="unknown"):
        detect(bars)


def test_duplicate_and_backward_times_rejected():
    for at in (T + 60, T - 60):
        bars = fixture()
        bars[2]["at"] = at
        with pytest.raises(ValueError, match="duplicate or backward"):
            detect(bars)


def test_source_tampering_changes_candidate_identity_and_snapshot():
    baseline = detect(fixture())
    changed = detect(fixture(), source=dict(SOURCE, provider="alternate"))
    assert baseline["snapshot_sha256"] != changed["snapshot_sha256"]
    assert baseline["candidates"][0]["path_id"] != changed["candidates"][0]["path_id"]


def test_snapshot_digest_binds_pre_signal_ohlc():
    bars = fixture()
    a = detect(bars)
    bars[0]["open"] = "100.1"
    b = detect(bars)
    assert a["snapshot_sha256"] != b["snapshot_sha256"]
    assert a["candidates"] == b["candidates"]


def test_inputs_unchanged():
    source, bars = deepcopy(SOURCE), fixture()
    before = deepcopy((source, bars))
    detect_completed_m1_confluence(source, bars, bars[-1]["at"] + 60)
    assert (source, bars) == before


@pytest.mark.parametrize("mutation", [
    {"archive_sha256": "bad"}, {"price_side": "TRADE"},
    {"horizon_minutes": True}, {"instrument": ""}, {"extra": "x"},
])
def test_source_identity_fail_closed(mutation):
    with pytest.raises(ValueError):
        detect(fixture(), source=dict(SOURCE, **mutation))


def test_empty_snapshot_is_not_publishable():
    with pytest.raises(ValueError, match="Nonempty"):
        detect_completed_m1_confluence(SOURCE, [], T)


def test_causal_atr_bridge_accepts_candidate_schema():
    from app.causal_atr_intent_bridge import compile_causal_atr_intents
    report = detect(fixture())
    compiled = compile_causal_atr_intents(SOURCE, report["candidates"])
    assert compiled["eligible_count"] == 1
    assert compiled["excluded_count"] == 0
    assert compiled["manifest"]["eligible_intents"][0]["signal_at"] == T + 21 * 60
    assert "entry" not in compiled["manifest"]["eligible_intents"][0]
