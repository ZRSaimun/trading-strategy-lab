"""Synthetic lineage tests. No historical performance, vendor data or broker orders."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.causal_m1_confluence_detector import detect_completed_m1_confluence
from app.causal_atr_intent_bridge import compile_causal_atr_intents
from app.causal_m1_lineage_audit import audit_causal_m1_lineage

T = int(datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc).timestamp())
SOURCE = dict(instrument="XAUUSD", provider="fixture", venue="fixture",
              archive_sha256="a" * 64, price_side="BID", horizon_minutes=1)


def bar(i, o="100", h="101", l="99", c="100"):
    return dict(at=T + i * 60, open=o, high=h, low=l, close=c)


def fixture(direction="LONG", confirmed=True):
    candles = [bar(i) for i in range(20)]
    if direction == "LONG":
        candles.append(bar(20, l="98"))
        if confirmed:
            candles.append(bar(21, o="102", h="104", l="101.5", c="103.5"))
    else:
        candles.append(bar(20, h="102"))
        if confirmed:
            candles.append(bar(21, o="98", h="98.5", l="96", c="96.5"))
    return candles


def expected(bars, source=None):
    source = source or SOURCE
    cutoff = bars[-1]["at"] + 60
    scan = detect_completed_m1_confluence(source, bars, cutoff)
    hashes = dict(expected_snapshot_sha256=scan["snapshot_sha256"])
    if scan["candidates"]:
        frozen = compile_causal_atr_intents(source, scan["candidates"])
        hashes.update(expected_manifest_sha256=frozen["manifest_sha256"],
                      expected_pre_signal_evidence_sha256=frozen["pre_signal_evidence_sha256"])
    return hashes


def audit(bars=None, source=None, **kwargs):
    bars = bars if bars is not None else fixture()
    source = source or SOURCE
    hashes = expected(bars, source)
    hashes.update(kwargs)
    return audit_causal_m1_lineage(source, bars, bars[-1]["at"] + 60, **hashes)


@pytest.mark.parametrize("direction", ["LONG", "SHORT"])
def test_complete_replay_links_candidate_to_frozen_intent(direction):
    r = audit(fixture(direction))
    assert r["confirmed_candidates"] == 1
    assert r["eligible_intents"] == 1
    assert r["declared_exclusions"] == 0
    assert r["candidate_samples"][0]["direction"] == direction
    assert r["candidate_samples"][0]["status"] == "FROZEN_ELIGIBLE"
    assert r["status"] == "COMPLETE_RECONSTRUCTION_NOT_VALIDATED_EDGE"
    assert r["pre_signal_population_reconciled"] is True
    assert r["verified_profitability"] is False
    assert r["may_execute_order"] is False
    assert "returns" not in r and "profit" not in r


def test_no_candidate_does_not_invent_backtest_or_hashes():
    r = audit(fixture(confirmed=False))
    assert r["status"] == "NO_CANDIDATES_NOT_A_BACKTEST"
    assert r["confirmed_candidates"] == 0
    assert r["pending_sweeps"] == 1
    assert r["manifest_sha256"] is None
    assert r["candidate_samples"] == []


def test_no_candidate_rejects_fabricated_manifest():
    with pytest.raises(ValueError, match="must be absent"):
        audit(fixture(confirmed=False), expected_manifest_sha256="b" * 64)


def test_snapshot_tampering_rejected_even_when_candidates_unchanged():
    bars = fixture()
    hashes = expected(bars)
    bars[0]["open"] = "100.1"
    with pytest.raises(ValueError, match="snapshot fingerprint mismatch"):
        audit_causal_m1_lineage(SOURCE, bars, bars[-1]["at"] + 60, **hashes)


def test_frozen_manifest_tampering_rejected():
    with pytest.raises(ValueError, match="manifest fingerprint mismatch"):
        audit(expected_manifest_sha256="b" * 64)


def test_pre_signal_evidence_tampering_rejected():
    with pytest.raises(ValueError, match="evidence fingerprint mismatch"):
        audit(expected_pre_signal_evidence_sha256="b" * 64)


def test_hashes_are_required_for_confirmed_candidates():
    with pytest.raises(ValueError, match="Expected manifest"):
        audit(expected_manifest_sha256=None)
    with pytest.raises(ValueError, match="Expected pre-signal evidence"):
        audit(expected_pre_signal_evidence_sha256=None)


def test_wrong_source_rejected_by_preserved_snapshot_hash():
    bars = fixture()
    hashes = expected(bars)
    with pytest.raises(ValueError, match="snapshot fingerprint mismatch"):
        audit_causal_m1_lineage(dict(SOURCE, provider="different"), bars,
                                bars[-1]["at"] + 60, **hashes)


def test_censored_gap_retained_as_a_count():
    bars = fixture()
    bars[21]["at"] += 60
    r = audit(bars)
    assert r["confirmed_candidates"] == 0
    assert r["gap_censored_sweeps"] == 1


def test_zero_samples_preserves_counts():
    r = audit(sample_limit=0)
    assert r["candidate_samples"] == []
    assert r["confirmed_candidates"] == 1


@pytest.mark.parametrize("limit", [True, -1, 51, 1.5])
def test_invalid_sample_limits_fail_closed(limit):
    with pytest.raises(ValueError, match="sample limit"):
        audit(sample_limit=limit)


@pytest.mark.parametrize("bad", ["BAD", "A" * 64, True, 123])
def test_bad_snapshot_hashes_fail_closed(bad):
    with pytest.raises(ValueError, match="SHA-256"):
        audit(expected_snapshot_sha256=bad)


def test_unknown_outcome_field_rejected():
    bars = fixture()
    bars[0]["future_return"] = "999"
    with pytest.raises(ValueError, match="unknown"):
        audit(bars)


def test_wrong_cutoff_rejected_even_with_preserved_digest():
    bars = fixture()
    hashes = expected(bars)
    with pytest.raises(ValueError, match="Last completed"):
        audit_causal_m1_lineage(SOURCE, bars, bars[-1]["at"] + 120, **hashes)


def test_inputs_unchanged():
    bars, source = fixture(), deepcopy(SOURCE)
    original = deepcopy((bars, source))
    audit(bars, source)
    assert (bars, source) == original


def test_detector_prefix_invariance_but_new_snapshot_hash():
    bars = fixture()
    older = detect_completed_m1_confluence(SOURCE, bars, bars[-1]["at"] + 60)
    extended = bars + [bar(22), bar(23)]
    newer = detect_completed_m1_confluence(SOURCE, extended, extended[-1]["at"] + 60)
    assert older["candidates"] == newer["candidates"]
    assert older["snapshot_sha256"] != newer["snapshot_sha256"]
    assert audit(extended)["confirmed_candidates"] == 1


def test_reject_silently_dropped_candidate_from_compiler(monkeypatch):
    from app import causal_m1_lineage_audit as module
    real = module.compile_causal_atr_intents

    def incomplete(source, candidates):
        output = real(source, candidates)
        output["manifest"]["eligible_intents"] = []
        return output

    monkeypatch.setattr(module, "compile_causal_atr_intents", incomplete)
    with pytest.raises(ValueError, match="population mismatch"):
        audit()


def test_reject_compiler_direction_mismatch(monkeypatch):
    from app import causal_m1_lineage_audit as module
    real = module.compile_causal_atr_intents

    def flipped(source, candidates):
        output = real(source, candidates)
        output["manifest"]["eligible_intents"][0]["direction"] = "SHORT"
        return output

    monkeypatch.setattr(module, "compile_causal_atr_intents", flipped)
    with pytest.raises(ValueError, match="direction mismatch"):
        audit()
