"""Synthetic causal issuance-census regressions, never forward market evidence."""
from copy import deepcopy
import pytest

from app.forecast_issuance_census import audit_issuance_opportunities

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH", "venue": "TEST",
            "sourceId": "census", "priceSide": "bid", "seconds": 60}


def snapshot(*, forecast=True, gap=False, lag=30):
    candles = [0, 60, 180] if gap else [0, 60, 120]
    events = []
    for base in candles:
        events.append({"seq": len(events) + 1, "kind": "CANDLE", "start": base,
                       "close": 100.0 + base / 60, "receivedAt": base + 60})
        if forecast and base == 0:
            events.append({"seq": len(events) + 1, "kind": "FORECAST", "id": "a-1",
                           "modelVersion": "modelA", "horizon": 1,
                           "probability": 0.6, "baseStart": 0, "receivedAt": 60})
    # A full event replay settles the first forecast on the next candle.
    from app.forecast_event_store import _replay
    payload = {"version": 1, "identity": IDENTITY.copy(), "maxLagSeconds": lag,
               "events": events}
    return {"sequence": len(events), "identity": IDENTITY.copy(), "maxLagSeconds": lag,
            "events": events, "forecasts": _replay(payload, 300),
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def audit(s=None, *, as_of=190, models=("modelA",), horizons=(1,)):
    return audit_issuance_opportunities(s or snapshot(), as_of=as_of,
                                       model_versions=models, horizons=horizons)


def test_counts_issued_missed_and_open():
    result = audit()
    row = result["groups"][0]
    assert (row["issued"], row["missed"], row["open"], row["ineligible"]) == (1, 1, 1, 0)
    assert row["missedBaseStartsSample"] == [60]
    assert row["observedCandleOpportunities"] == 3
    assert result["netReturn"] is None and result["liveOrdersPermitted"] is False


def test_last_open_becomes_missed_after_deadline():
    row = audit(as_of=211)["groups"][0]
    assert row["missed"] == 2 and row["open"] == 0


def test_unissued_model_is_not_invisible():
    rows = audit(models=("modelA", "modelB"))["groups"]
    assert rows[1]["issued"] == 0 and rows[1]["missed"] == 2 and rows[1]["open"] == 1


def test_horizons_are_separate_opportunities():
    rows = audit(horizons=(1, 3, 12))["groups"]
    assert [r["issued"] for r in rows] == [1, 0, 0]
    assert [r["missed"] for r in rows] == [1, 2, 2]


def test_empty_journal_is_not_claimed_complete_market_census():
    s = snapshot(forecast=False)
    s["events"] = []
    s["sequence"] = 0
    result = audit(s, as_of=190)
    assert result["observedCandles"] == 0
    assert result["journalCoversAllMarketCandles"] is False
    assert result["groups"][0]["observedCandleOpportunities"] == 0
    assert result["groups"][0]["completeOnObservedCandles"] is False


def test_gap_is_observed_not_assumed_missing_trading_session():
    result = audit(snapshot(gap=True), as_of=300)
    assert result["observedInterCandleGaps"] == 1
    assert result["marketSessionVerified"] is False


def test_candle_arrives_too_late_for_issuance_window():
    s = snapshot(forecast=False, lag=60)
    s["events"][0]["receivedAt"] = 120
    # Late candle cannot precede next candle receipt; construct a single-candle journal.
    s["events"] = [s["events"][0]]
    s["sequence"] = 1
    from app.forecast_event_store import _replay
    s["forecasts"] = _replay({"version": 1, "identity": IDENTITY.copy(),
                              "maxLagSeconds": 60, "events": s["events"]}, 150)
    row = audit(s, as_of=150)["groups"][0]
    assert row["ineligible"] == 1 and row["missed"] == 0


@pytest.mark.parametrize("mutation", [
    lambda s: s["forecasts"][0].update(status="SETTLED", outcomeUp=False),
    lambda s: s["forecasts"][0].update(resolvedAt=61),
    lambda s: s["events"][1].update(probability=.9),
    lambda s: s["events"][1].update(receivedAt=10),
    lambda s: s["events"][1].update(baseStart=60),
    lambda s: s["events"][1].update(id="changed"),
    lambda s: s["events"][0].update(close=-1),
    lambda s: s.update(sequence=999),
    lambda s: s.update(evidence="AUTHENTICATED"),
    lambda s: s["identity"].update(priceSide="executable"),
])
def test_tampered_or_forged_journal_fails_closed(mutation):
    s = snapshot()
    mutation(s)
    with pytest.raises(ValueError):
        audit(s)


@pytest.mark.parametrize("models,horizons,as_of", [
    ([], (1,), 190), (("modelA", "modelA"), (1,), 190),
    (("bad model",), (1,), 190), (("modelA",), (2,), 190),
    (("modelA",), (1, 1), 190), (("modelA",), (True,), 190),
    (("modelA",), (1,), -1), (("modelA",), (1,), True),
])
def test_invalid_policy_rejected(models, horizons, as_of):
    with pytest.raises(ValueError):
        audit(models=models, horizons=horizons, as_of=as_of)


def test_undeclared_issued_model_rejected():
    with pytest.raises(ValueError):
        audit(models=("modelB",))


def test_as_of_before_journal_event_rejected():
    with pytest.raises(ValueError):
        audit(as_of=179)


def test_deterministic_no_side_effects():
    s = snapshot()
    old = deepcopy(s)
    assert audit(s) == audit(s)
    assert s == old
