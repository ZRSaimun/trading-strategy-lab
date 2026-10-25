"""Synthetic disconnected tests: no authenticated feed or profitable returns."""
import pytest
from app.forecast_frozen_baseline_audit import audit_frozen_baseline

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC", "venue": "TEST",
            "sourceId": "baseline-audit", "priceSide": "bid", "seconds": 60}
BASE = {"baselineId": "frozen-climatology-v1", "modelVersion": "m1",
        "horizonCandles": 1, "baselineProbability": .5, "frozenAt": 100}


def snapshot(n=30, p=.7, y=True, status="SETTLED"):
    events, forecasts = [], []
    for i in range(n):
        start = 120 + i * 60
        issued = start + 60
        fid = f"f{i}"
        base_close = 100 + i if y else 100 - i
        events.append({"seq": len(events) + 1, "kind": "CANDLE", "start": start,
                       "close": base_close, "receivedAt": issued})
        events.append({"seq": len(events) + 1, "kind": "FORECAST", "id": fid,
                       "modelVersion": "m1", "horizon": 1, "probability": p,
                       "baseStart": start, "receivedAt": issued})
        forecasts.append({"id": fid, "modelVersion": "m1", "horizon": 1,
                          "probability": p, "baseStart": start, "baseClose": base_close,
                          "issuedAt": issued, "targetStart": start + 60,
                          "status": status, "resolvedAt": issued + 60 if status != "PENDING" else None,
                          "outcomeUp": y if status == "SETTLED" else None})
    if n:
        last_start = 120 + n * 60
        events.append({"seq": len(events) + 1, "kind": "CANDLE", "start": last_start,
                       "close": 100 + n if y else 100 - n,
                       "receivedAt": last_start + 60})
    return {"sequence": len(events), "identity": IDENTITY.copy(),
            "maxLagSeconds": 120, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def audit(s=None, b=None, **kw):
    settings = {"window_start": 150, "window_end": 6000, "as_of": 6500}
    settings.update(kw)
    return audit_frozen_baseline(s if s is not None else snapshot(),
                                 b if b is not None else BASE.copy(), **settings)


def test_positive_skill_is_descriptive_not_trading_performance():
    r = audit()
    assert r["status"] == "DESCRIPTIVE_ONLY" and r["issued"] == 30
    assert r["modelBrier"] == pytest.approx(.09)
    assert r["baselineBrier"] == pytest.approx(.25)
    assert r["brierSkill"] == pytest.approx(.64)
    assert r["meanPairedExcessLoss"] == pytest.approx(-.16)
    assert r["maxCumulativeExcessLoss"] == 0
    assert not r["sourceAuthenticated"] and not r["mayExecutePaperOrder"]
    assert r["netReturn"] is None and r["maximumTradingDrawdown"] is None


def test_negative_skill_and_downside_excess_loss():
    r = audit(snapshot(p=.7, y=False))
    assert r["brierSkill"] == pytest.approx(-.96)
    assert r["worstPairedExcessLoss"] == pytest.approx(.24)
    assert r["maxCumulativeExcessLoss"] == pytest.approx(7.2)


def test_censoring_withholds_all_scores():
    for status in ("PENDING", "VOID_GAP"):
        s = snapshot()
        s["forecasts"][0].update(status=status, outcomeUp=None,
                                  resolvedAt=None if status == "PENDING" else 240)
        r = audit(s)
        assert r["status"] == "WITHHELD_CENSORED"
        assert r["modelBrier"] is None and r["brierSkill"] is None


def test_asof_late_settlement_withheld():
    s = snapshot()
    s["forecasts"][0]["resolvedAt"] = 6600
    r = audit(s)
    assert r["status"] == "WITHHELD_CENSORED" and r["settledAfterAsOf"] == 1


def test_immature_target_withheld():
    r = audit(snapshot(), window_end=1930, as_of=1930)
    assert r["status"] == "WITHHELD_CENSORED" and r["notMatureAsOf"] >= 1


def test_small_sample_withheld():
    r = audit(snapshot(29))
    assert r["status"] == "INSUFFICIENT_SAMPLE" and r["brierSkill"] is None


def test_no_issuances_in_window():
    r = audit(snapshot(), window_start=110, window_end=150, as_of=6500)
    assert r["status"] == "INSUFFICIENT_SAMPLE" and r["issued"] == 0


def test_other_model_horizon_is_not_pooled():
    s = snapshot()
    s["events"][1]["modelVersion"] = "other"
    s["forecasts"][0]["modelVersion"] = "other"
    assert audit(s)["status"] == "INSUFFICIENT_SAMPLE"


@pytest.mark.parametrize("change", [
    lambda s: s.update(evidence="AUTHENTICATED_LIVE"),
    lambda s: s.update(sequence=1),
    lambda s: s["events"][0].update(seq=9),
    lambda s: s["events"][1].update(probability=.8),
    lambda s: s["forecasts"][0].update(probability=float("nan")),
    lambda s: s["forecasts"][0].update(outcomeUp=1),
    lambda s: s["forecasts"][0].update(targetStart=999),
    lambda s: s["forecasts"][0].update(id="bad"),
    lambda s: s["forecasts"][0].update(status="LIVE"),
    lambda s: s["forecasts"][0].update(resolvedAt=0),
    lambda s: s["forecasts"][0].update(resolvedAt=180),
    lambda s: s["forecasts"][0].update(issuedAt=120),
    lambda s: s["identity"].update(priceSide="executable"),
])
def test_malformed_snapshot_rejected(change):
    s = snapshot()
    change(s)
    with pytest.raises(ValueError):
        audit(s)


@pytest.mark.parametrize("change", [
    lambda b: b.update(frozenAt=150),
    lambda b: b.update(frozenAt=True),
    lambda b: b.update(baselineProbability=0),
    lambda b: b.update(baselineProbability=1),
    lambda b: b.update(baselineProbability=float("nan")),
    lambda b: b.update(horizonCandles=2),
    lambda b: b.update(horizonCandles=True),
    lambda b: b.update(baselineId=""),
    lambda b: b.update(unknown=True),
])
def test_invalid_frozen_baseline_rejected(change):
    b = BASE.copy()
    change(b)
    with pytest.raises(ValueError):
        audit(b=b)


def test_window_and_min_sample_gates():
    for kwargs in ({"window_start": 6000, "window_end": 6000, "as_of": 6500},
                   {"window_start": 150, "window_end": 6501, "as_of": 6500},
                   {"window_start": True, "window_end": 6000, "as_of": 6500},
                   {"window_start": 150, "window_end": 6000, "as_of": 6500, "min_settled": 29}):
        with pytest.raises(ValueError):
            audit_frozen_baseline(snapshot(), BASE, **kwargs)
