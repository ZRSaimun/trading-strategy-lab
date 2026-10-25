"""Synthetic, disconnected durable forecast-review outbox regressions."""
import json

import pytest
from sqlalchemy import create_engine, select, event
from sqlalchemy.orm import sessionmaker

from app.db import Base, Audit, Record
from app.forecast_event_store import ForecastEventStore
from app.forecast_alert_outbox import ForecastAlertOutbox

FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC", "venue": "TEST",
        "sourceId": "alerts", "priceSide": "bid", "seconds": 60}
SESSION = "outbox-fixture"
FID = "forecast-a"


@pytest.fixture
def state(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "alerts.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    clock = [120]
    journal = ForecastEventStore(factory, lambda: clock[0])
    outbox = ForecastAlertOutbox(factory, lambda: clock[0])
    assert journal.append(SESSION, FEED, 120, 0, {"kind": "CANDLE", "start": 60, "close": 100})
    assert journal.append_forecasts_atomic(SESSION, FEED, 120, 1, [
        {"kind": "FORECAST", "id": FID, "modelVersion": "baseline", "horizon": 1,
         "probability": .6, "baseStart": 60}])
    yield outbox, journal, factory, clock
    engine.dispose()


def test_only_persisted_forecasts_may_queue(state):
    outbox, _, _, _ = state
    with pytest.raises(ValueError, match="missing"):
        outbox.queue(SESSION, FEED, "unknown")
    with pytest.raises(ValueError, match="source mismatch"):
        outbox.queue(SESSION, {**FEED, "provider": "OTHER"}, FID)
    assert outbox.read(SESSION, FID) is None
    assert outbox.queue(SESSION, FEED, FID)
    assert outbox.queue(SESSION, FEED, FID) is False
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"


def test_claim_is_one_shot_and_ack_never_verified(state):
    outbox, _, _, _ = state
    outbox.queue(SESSION, FEED, FID)
    claimed = outbox.claim(SESSION, FID)
    assert claimed["status"] == "IN_FLIGHT_UNCERTAIN"
    assert len(claimed["claimId"]) == 32
    assert outbox.claim(SESSION, FID) is None
    assert outbox.acknowledge_unverified(SESSION, FID, "wrong") is None
    ack = outbox.acknowledge_unverified(SESSION, FID, claimed["claimId"])
    assert ack["status"] == "ACK_RECORDED_UNVERIFIED"
    assert ack["deliveryVerified"] is False
    assert ack["mayExecuteLiveOrder"] is False
    assert outbox.acknowledge_unverified(SESSION, FID, claimed["claimId"]) is None


def test_restart_keeps_uncertain_claim_and_blocks_resend(state):
    outbox, _, factory, clock = state
    outbox.queue(SESSION, FEED, FID)
    claim = outbox.claim(SESSION, FID)
    restarted = ForecastAlertOutbox(factory, lambda: clock[0])
    assert restarted.read(SESSION, FID)["claimId"] == claim["claimId"]
    assert restarted.claim(SESSION, FID) is None
    assert restarted.queue(SESSION, FEED, FID) is False


def test_expired_queue_cannot_claim(state):
    outbox, _, _, clock = state
    outbox.queue(SESSION, FEED, FID)
    clock[0] = 180
    assert outbox.read(SESSION, FID)["status"] == "EXPIRED_UNCLAIMED"
    assert outbox.claim(SESSION, FID) is None
    assert outbox.cancel_unclaimed(SESSION, FID) is None


def test_expired_forecast_cannot_be_newly_queued(state):
    outbox, _, _, clock = state
    clock[0] = 180
    with pytest.raises(ValueError, match="expired"):
        outbox.queue(SESSION, FEED, FID)


def test_cancel_only_before_claim(state):
    outbox, _, _, _ = state
    outbox.queue(SESSION, FEED, FID)
    assert outbox.cancel_unclaimed(SESSION, FID)["status"] == "CANCELLED"
    assert outbox.claim(SESSION, FID) is None
    assert outbox.cancel_unclaimed(SESSION, FID) is None


def test_claim_cannot_be_cancelled_even_if_uncertain(state):
    outbox, _, _, _ = state
    outbox.queue(SESSION, FEED, FID)
    outbox.claim(SESSION, FID)
    assert outbox.cancel_unclaimed(SESSION, FID) is None


def test_audit_writes_and_no_duplicate_queue(state):
    outbox, _, factory, _ = state
    outbox.queue(SESSION, FEED, FID)
    outbox.queue(SESSION, FEED, FID)
    outbox.claim(SESSION, FID)
    with factory() as db:
        actions = [a.action for a in db.scalars(select(Audit).order_by(Audit.id))]
    assert actions.count("forecast.alert.queue") == 1
    assert actions.count("forecast.alert.claim") == 1


def test_corrupt_digest_is_rejected_without_mutation(state):
    outbox, _, factory, _ = state
    outbox.queue(SESSION, FEED, FID)
    key = outbox._key(SESSION, FID)
    with factory() as db:
        row = db.get(Record, key)
        envelope = json.loads(row.value)
        envelope["sha256"] = "0" * 64
        row.value = json.dumps(envelope)
        db.commit()
    with pytest.raises(ValueError, match="integrity failure"):
        outbox.read(SESSION, FID)
    with pytest.raises(ValueError, match="integrity failure"):
        outbox.claim(SESSION, FID)


@pytest.mark.parametrize("bad", [True, 0, 3601, -1, 3.5])
def test_invalid_age_budget_rejected(state, bad):
    outbox, _, _, _ = state
    with pytest.raises(ValueError, match="age budget"):
        outbox.queue(SESSION, FEED, FID, bad)


def test_no_unpersisted_or_settled_forecast_can_queue(state):
    outbox, journal, _, clock = state
    clock[0] = 180
    assert journal.append(SESSION, FEED, 120, 2, {"kind": "CANDLE", "start": 120, "close": 101})
    with pytest.raises(ValueError, match="no longer pending"):
        outbox.queue(SESSION, FEED, FID)


def test_two_independent_instances_do_not_duplicate_claim(state):
    outbox, _, factory, clock = state
    outbox.queue(SESSION, FEED, FID)
    another = ForecastAlertOutbox(factory, lambda: clock[0])
    first = outbox.claim(SESSION, FID)
    assert first["status"] == "IN_FLIGHT_UNCERTAIN"
    assert another.claim(SESSION, FID) is None


def test_queued_forecast_does_not_authorize_delivery_or_trading(state):
    outbox, _, _, _ = state
    outbox.queue(SESSION, FEED, FID)
    view = outbox.read(SESSION, FID)
    assert all(view[k] is False for k in (
        "sourceAuthenticated", "deliveryVerified", "notificationEnabled",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_queue_audit_failure_rolls_back_record(state):
    outbox, _, factory, _ = state
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def injected_failure(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic audit crash")

    try:
        with pytest.raises(RuntimeError, match="synthetic audit crash"):
            outbox.queue(SESSION, FEED, FID)
    finally:
        event.remove(engine, "before_cursor_execute", injected_failure)
    assert outbox.read(SESSION, FID) is None
    assert outbox.queue(SESSION, FEED, FID) is True


def test_claim_audit_failure_preserves_queued_state(state):
    outbox, _, factory, _ = state
    outbox.queue(SESSION, FEED, FID)
    engine = factory.kw["bind"]

    @event.listens_for(engine, "before_cursor_execute")
    def injected_failure(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic claim audit crash")

    try:
        with pytest.raises(RuntimeError, match="synthetic claim audit crash"):
            outbox.claim(SESSION, FID)
    finally:
        event.remove(engine, "before_cursor_execute", injected_failure)
    assert outbox.read(SESSION, FID)["status"] == "QUEUED"
    assert outbox.claim(SESSION, FID)["status"] == "IN_FLIGHT_UNCERTAIN"
