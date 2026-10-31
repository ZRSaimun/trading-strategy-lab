"""Synthetic disconnected tests; no market feed or trading outcome is asserted."""
import pytest
from app.forecast_maturity_audit import audit_forecast_maturity

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "TEST", "venue": "TEST",
            "sourceId": "offline", "priceSide": "bid", "seconds": 60}


def snapshot(status="PENDING", horizon=1):
    issued_at = 120
    target = 60 + horizon * 60
    resolution = target + 60 if status == "SETTLED" else (180 if status == "VOID_GAP" else None)
    return {"sequence": 2, "identity": IDENTITY.copy(), "maxLagSeconds": 120,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL",
            "events": [{"seq": 1, "kind": "CANDLE", "start": 60, "close": 100, "receivedAt": 120},
                       {"seq": 2, "kind": "FORECAST", "id": "f1", "modelVersion": "baseline",
                        "horizon": horizon, "probability": .7, "baseStart": 60, "receivedAt": issued_at}],
            "forecasts": [{"id": "f1", "modelVersion": "baseline", "horizon": horizon,
                           "probability": .7, "baseStart": 60, "baseClose": 100,
                           "issuedAt": issued_at, "targetStart": target, "status": status,
                           "resolvedAt": resolution, "outcomeUp": True if status == "SETTLED" else None}]}


def row(s, as_of=360, **kw):
    return audit_forecast_maturity(s, as_of=as_of, **kw)["groups"][0]


def test_overdue_pending_is_not_silently_scored():
    result = audit_forecast_maturity(snapshot(), as_of=360)
    r = result["groups"][0]
    assert r["pendingOverdue"] == 1 and r["settled"] == 0
    assert r["settledFractionOfMatured"] == 0
    assert result["profitabilityEstablished"] is False and result["netReturn"] is None
    assert result["sourceAuthenticated"] is False


def test_not_due_at_exact_boundary_minus_one():
    r = row(snapshot(), as_of=299)
    assert r["pendingNotDue"] == 1 and r["maturedOrOverdue"] == 0
    assert r["settledFractionOfMatured"] is None


def test_due_exactly_at_boundary():
    assert row(snapshot(), as_of=300)["pendingOverdue"] == 1


def test_grace_defers_overdue():
    assert row(snapshot(), as_of=360, grace_seconds=61)["pendingNotDue"] == 1
    assert row(snapshot(), as_of=361, grace_seconds=61)["pendingOverdue"] == 1


def test_settled_and_void_gap_are_separate():
    settled = row(snapshot("SETTLED"), as_of=300)
    void = row(snapshot("VOID_GAP"), as_of=300)
    assert settled["settledFractionOfMatured"] == 1
    assert void["settledFractionOfMatured"] == 0
    assert void["requiresReconciliation"] is True


def test_long_horizon_not_falsely_overdue():
    assert row(snapshot(horizon=12), as_of=360)["pendingNotDue"] == 1


def test_empty_snapshot():
    s = snapshot()
    s["events"] = []
    s["forecasts"] = []
    s["sequence"] = 0
    assert audit_forecast_maturity(s, as_of=360)["groups"] == []


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(evidence="AUTHENTICATED_LIVE"),
    lambda s: s.update(sequence=999),
    lambda s: s["identity"].update(priceSide="executable"),
    lambda s: s["events"][1].update(id="different"),
    lambda s: s["events"][1].update(receivedAt=361),
    lambda s: s["forecasts"][0].update(probability=float("nan")),
    lambda s: s["forecasts"][0].update(outcomeUp=True),
    lambda s: s["forecasts"][0].update(targetStart=999),
    lambda s: s["forecasts"][0].update(status="DELIVERED"),
    lambda s: s["forecasts"][0].update(baseStart=61),
    lambda s: s["forecasts"][0].update(issuedAt=180),
    lambda s: s["forecasts"][0].update(baseClose=-1),
])
def test_rejects_inconsistent_snapshots(mutation):
    s = snapshot()
    mutation(s)
    with pytest.raises(ValueError):
        row(s)


@pytest.mark.parametrize("as_of,grace", [(True, 0), (-1, 0), (360, True), (360, -1), (360, 86401)])
def test_rejects_invalid_settings(as_of, grace):
    with pytest.raises(ValueError):
        audit_forecast_maturity(snapshot(), as_of=as_of, grace_seconds=grace)


def test_rejects_early_settlement():
    s = snapshot("SETTLED")
    s["forecasts"][0]["resolvedAt"] = 179
    with pytest.raises(ValueError, match="Settlement before"):
        row(s)


def test_rejects_future_resolution():
    s = snapshot("SETTLED")
    s["forecasts"][0]["resolvedAt"] = 500
    with pytest.raises(ValueError):
        row(s)
