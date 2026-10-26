"""Synthetic-only causal paired forecast comparison regressions."""
from copy import deepcopy
import math
import pytest

from app.forecast_event_store import _replay
from app.forecast_challenger_audit import compare_prospective_models

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC",
            "venue": "TEST", "sourceId": "paired-test", "priceSide": "bid",
            "seconds": 60}


def snapshot(n=30, horizon=1, final=True, omit=None, gap=None, old_p=.4, new_p=.8):
    """Generate genuine replayable causal events, not hand-forged outcomes."""
    events = []
    for i in range(n + horizon if final else n):
        if i == gap:
            continue
        start = i * 60
        at = start + 60
        events.append({"seq": len(events) + 1, "kind": "CANDLE",
                       "receivedAt": at, "start": start, "close": 100 + i})
        if i >= n:
            continue
        for model, p in (("incumbent", old_p), ("challenger", new_p)):
            if omit == (i, model):
                continue
            events.append({"seq": len(events) + 1, "kind": "FORECAST",
                           "receivedAt": at, "id": f"{model}-{i}",
                           "modelVersion": model, "horizon": horizon,
                           "probability": p, "baseStart": start})
    as_of = events[-1]["receivedAt"]
    forecasts = _replay({"version": 1, "identity": IDENTITY,
                         "maxLagSeconds": 0, "events": events}, as_of)
    return {"sequence": len(events), "identity": IDENTITY.copy(),
            "maxLagSeconds": 0, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}, as_of


def evaluate(s=None, as_of=None, horizon=1, **kwargs):
    if s is None:
        s, as_of = snapshot(horizon=horizon)
    return compare_prospective_models(s, incumbent="incumbent",
                                      challenger="challenger", horizon=horizon,
                                      as_of=as_of, **kwargs)


@pytest.mark.parametrize("horizon", [1, 3, 12])
def test_paired_brier_horizon_isolation(horizon):
    s, at = snapshot(horizon=horizon)
    r = evaluate(s, at, horizon=horizon)
    assert r["status"] == "REPORT" and r["settledPairs"] == 30
    assert r["incumbentBrier"] == pytest.approx(.36)
    assert r["challengerBrier"] == pytest.approx(.04)
    assert r["meanExcessBrier"] == pytest.approx(-.32)
    assert r["brierSkillVsIncumbent"] == pytest.approx(1 - .04 / .36)
    assert r["maxCumulativeExcessBrierDrawdown"] == 0
    assert r["netReturn"] is None and r["maximumTradingDrawdown"] is None
    assert not r["sourceAuthenticated"] and not r["mayExecutePaperOrder"]
    assert not r["mayExecuteLiveOrder"]


def test_adverse_challenger_loss_is_probability_not_cash_drawdown():
    s, at = snapshot(old_p=.8, new_p=.4)
    r = evaluate(s, at)
    assert r["meanExcessBrier"] == pytest.approx(.32)
    assert r["maxCumulativeExcessBrierDrawdown"] == pytest.approx(30 * .32)
    assert r["worstSingleExcessBrier"] == pytest.approx(.32)


def test_missing_challenger_withholds_every_score():
    s, at = snapshot(omit=(5, "challenger"))
    r = evaluate(s, at)
    assert r["status"] == "WITHHELD" and r["reason"] == "UNPAIRED_FORECASTS"
    assert r["unpairedBaseCandles"] == 1 and r["settledPairs"] == 29
    assert r["meanExcessBrier"] is None


def test_pending_withholds_even_with_thirty_settled():
    s, at = snapshot(n=31, final=False)
    r = evaluate(s, at)
    assert r["reason"] == "PENDING_OR_VOID_OUTCOMES"
    assert r["unresolvedPairs"] >= 1 and r["meanExcessBrier"] is None


def test_missing_completed_candle_voids_and_withholds():
    s, at = snapshot(gap=15)
    r = evaluate(s, at)
    assert r["status"] == "WITHHELD"
    assert r["unresolvedPairs"] >= 1


def test_below_minimum_withholds():
    s, at = snapshot(n=29)
    r = evaluate(s, at)
    assert r["reason"] == "INSUFFICIENT_PAIRS"
    assert r["settledPairs"] == 29


def test_empty_journal_withholds():
    s, at = snapshot(n=0)
    r = evaluate(s, at)
    assert r["status"] == "WITHHELD" and r["baseCandles"] == 0


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(evidence="AUTHENTICATED_LIVE"),
    lambda s: s.update(sequence=1),
    lambda s: s["forecasts"][0].update(probability=.99),
    lambda s: s["forecasts"][0].update(outcomeUp=False),
    lambda s: s["forecasts"][0].update(status="PENDING"),
    lambda s: s["events"][0].update(close=0),
    lambda s: s["events"][1].update(probability=float("nan")),
    lambda s: s["events"][1].update(receivedAt=0),
    lambda s: s["events"][1].update(baseStart=999),
    lambda s: s["identity"].update(priceSide="executable"),
    lambda s: s.update(maxLagSeconds=-1),
])
def test_rejects_modified_or_invalid_causal_journal(mutation):
    s, at = snapshot()
    s = deepcopy(s)
    mutation(s)
    with pytest.raises(ValueError):
        evaluate(s, at)


@pytest.mark.parametrize("config", [
    {"incumbent": "same", "challenger": "same", "horizon": 1, "as_of": 100},
    {"incumbent": "a", "challenger": "b", "horizon": True, "as_of": 100},
    {"incumbent": "a", "challenger": "b", "horizon": 2, "as_of": 100},
    {"incumbent": "a", "challenger": "b", "horizon": 1, "as_of": -1},
    {"incumbent": "a", "challenger": "b", "horizon": 1, "as_of": 100, "min_pairs": 29},
    {"incumbent": "a", "challenger": "b", "horizon": 1, "as_of": 100, "min_pairs": True},
])
def test_invalid_configurations_fail_closed(config):
    s, _ = snapshot()
    with pytest.raises(ValueError):
        compare_prospective_models(s, **config)


def test_as_of_cannot_precede_last_journal_receipt():
    s, at = snapshot()
    with pytest.raises(ValueError):
        evaluate(s, at - 1)


def test_independent_copies_deterministic():
    s, at = snapshot()
    assert evaluate(s, at) == evaluate(deepcopy(s), at)


def test_no_division_by_zero_for_perfect_incumbent():
    s, at = snapshot(old_p=.999999, new_p=.8)
    r = evaluate(s, at)
    assert r["status"] == "REPORT"
    assert math.isfinite(r["brierSkillVsIncumbent"])
