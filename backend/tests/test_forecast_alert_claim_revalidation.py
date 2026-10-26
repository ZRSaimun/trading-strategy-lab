"""Disconnected claim-time journal revalidation regressions (synthetic only)."""

import json

import pytest
from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base, Record
from app.forecast_alert_outbox import ForecastAlertOutbox
from app.forecast_event_store import ForecastEventStore

IDENTITY = {
    "instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC",
    "venue": "TEST", "sourceId": "claim-gate", "priceSide": "bid",
    "seconds": 60,
}
SESSION = "claim-gate-fixture"
FID = "long-horizon"


@pytest.fixture
def system(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "claim-gate.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    now = [120]
    journal = ForecastEventStore(factory, lambda: now[0])
    outbox = ForecastAlertOutbox(factory, lambda: now[0])
    assert journal.append(
        SESSION, IDENTITY, 0, 0, {"kind": "CANDLE", "start": 60, "close": 100}
    )
    assert journal.append_forecasts_atomic(
        SESSION, IDENTITY, 0, 1, [{
            "kind": "FORECAST", "id": FID, "modelVersion": "baseline",
            "horizon": 12, "probability": 0.6, "baseStart": 60,
        }]
    )
    assert outbox.queue(SESSION, IDENTITY, FID, max_age_seconds=300)
    yield journal, outbox, factory, now
    engine.dispose()


def _claim_audits(factory):
    with factory() as db:
        return list(db.scalars(
            select(Audit).where(Audit.action == "forecast.alert.claim")
        ))


def test_valid_pending_forecast_claim_still_works(system):
    _, outbox, factory, _ = system
    claim = outbox.claim(SESSION, FID)
    assert claim["status"] == "IN_FLIGHT_UNCERTAIN"
    assert claim["sourceAuthenticated"] is False
    assert claim["deliveryVerified"] is False
    assert claim["mayExecuteLiveOrder"] is False
    assert len(_claim_audits(factory)) == 1


def test_voided_forecast_gap_blocks_unexpired_queued_alert(system):
    journal, outbox, factory, now = system
    now[0] = 240
    # The 120-start candle is absent. A later completed candle voids the
    # horizon-12 forecast, but the alert's 300s age budget has not elapsed.
    assert journal.append(
        SESSION, IDENTITY, 0, 2, {"kind": "CANDLE", "start": 180, "close": 99}
    )
    snapshot = journal.load(SESSION)
    assert snapshot["forecasts"][0]["status"] == "VOID_GAP"
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"
    assert outbox.claim(SESSION, FID) is None
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"
    assert _claim_audits(factory) == []


def test_missing_journal_fails_closed_without_claim_audit(system):
    _, outbox, factory, _ = system
    with factory() as db:
        db.execute(delete(Record).where(
            Record.key == ForecastEventStore._key(SESSION)
        ))
        db.commit()
    with pytest.raises(ValueError, match="journal missing"):
        outbox.claim(SESSION, FID)
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"
    assert _claim_audits(factory) == []


def test_corrupted_journal_fails_closed_without_claim_audit(system):
    _, outbox, factory, _ = system
    with factory() as db:
        record = db.get(Record, ForecastEventStore._key(SESSION))
        envelope = json.loads(record.value)
        envelope["sha256"] = "0" * 64
        record.value = json.dumps(envelope)
        db.commit()
    with pytest.raises(ValueError, match="corrupt"):
        outbox.claim(SESSION, FID)
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"
    assert _claim_audits(factory) == []


@pytest.mark.parametrize("field,value", [
    ("issueSeq", 999),
    ("modelVersion", "different-model"),
    ("horizon", 3),
    ("baseStart", 120),
    ("issuedAt", 119),
])
def test_mismatched_outbox_linkage_cannot_claim(system, field, value):
    _, outbox, factory, now = system
    with factory() as db:
        record = db.get(Record, outbox._key(SESSION, FID))
        state = outbox._unpack(record.value, now[0])
        state[field] = value
        record.value = outbox._pack(state)
        db.commit()
    assert outbox.claim(SESSION, FID) is None
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"
    assert _claim_audits(factory) == []
