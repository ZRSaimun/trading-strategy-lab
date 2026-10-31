"""Offline integration contract: journal -> outbox -> formatter -> fake transport.

This suite NEVER contacts Telegram, authenticates a market feed, or executes a
paper/live order. The fake provider ACK proves only simulated API acceptance.
"""
import json
from io import BytesIO

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.forecast_event_store import ForecastEventStore
from app.forecast_alert_outbox import ForecastAlertOutbox
from app.forecast_review_message import render_unverified_forecast_review
from app.forecast_telegram_transport import DeliveryUncertain, send_telegram_once


FEED = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTHETIC",
        "venue": "TEST", "sourceId": "fake-receipts", "priceSide": "bid",
        "seconds": 60}
SESSION = "integration-rehearsal"
FORECAST = "forecast-001"
TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWX0123456789"
CHAT = "-1001234567890"


class FakeReply:
    status = 200

    def __init__(self, payload):
        self.body = BytesIO(payload)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit):
        return self.body.read(limit)


class FakeOpener:
    def __init__(self, *, corrupt_echo=False, failure=None):
        self.corrupt_echo = corrupt_echo
        self.failure = failure
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.failure is not None:
            raise self.failure
        outgoing = json.loads(request.data.decode("utf-8"))
        echoed = "different message" if self.corrupt_echo else outgoing["text"]
        payload = json.dumps({"ok": True, "result": {
            "message_id": 81, "chat": {"id": int(CHAT)}, "text": echoed
        }}).encode("utf-8")
        return FakeReply(payload)


@pytest.fixture
def pipeline(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "pipeline.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    clock = [120]
    journal = ForecastEventStore(factory, lambda: clock[0])
    outbox = ForecastAlertOutbox(factory, lambda: clock[0])
    assert journal.append(SESSION, FEED, 120, 0,
                          {"kind": "CANDLE", "start": 60, "close": 100.0})
    assert journal.append_forecasts_atomic(SESSION, FEED, 120, 1, [{
        "kind": "FORECAST", "id": FORECAST, "modelVersion": "baseline-v1",
        "horizon": 3, "probability": 0.6, "baseStart": 60
    }])
    assert outbox.queue(SESSION, FEED, FORECAST)
    yield journal, outbox, factory, clock
    engine.dispose()


def render(journal, outbox, clock):
    return render_unverified_forecast_review(
        journal.load(SESSION), outbox.read(SESSION, FORECAST),
        forecast_id=FORECAST, as_of=clock[0])


def test_one_claim_one_fake_acceptance_one_self_attested_ack(pipeline):
    journal, outbox, _factory, clock = pipeline
    message = render(journal, outbox, clock)
    assert "UNVERIFIED RESEARCH" in message
    assert "NO BUY/SELL SIGNAL" in message
    claim = outbox.claim(SESSION, FORECAST)
    assert claim["status"] == "IN_FLIGHT_UNCERTAIN"
    fake = FakeOpener()
    accepted = send_telegram_once(
        bot_token=TOKEN, chat_id=CHAT, text=message, opener=fake)
    assert accepted["providerAccepted"] is True
    assert accepted["deliveryVerified"] is False
    assert accepted["mayExecutePaperOrder"] is False
    assert accepted["mayExecuteLiveOrder"] is False
    assert len(fake.calls) == 1
    ack = outbox.acknowledge_unverified(
        SESSION, FORECAST, claim["claimId"])
    assert ack["status"] == "ACK_RECORDED_UNVERIFIED"
    assert ack["deliveryVerified"] is False
    assert outbox.claim(SESSION, FORECAST) is None
    assert outbox.acknowledge_unverified(
        SESSION, FORECAST, claim["claimId"]) is None


@pytest.mark.parametrize("mode", ["wrong_echo", "timeout"])
def test_ambiguous_provider_never_retries_or_self_acks(pipeline, mode):
    journal, outbox, _factory, clock = pipeline
    message = render(journal, outbox, clock)
    claim = outbox.claim(SESSION, FORECAST)
    fake = (FakeOpener(corrupt_echo=True) if mode == "wrong_echo"
            else FakeOpener(failure=TimeoutError("secret token")))
    with pytest.raises(DeliveryUncertain) as err:
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT,
                           text=message, opener=fake)
    assert TOKEN not in str(err.value)
    assert "secret" not in str(err.value)
    assert len(fake.calls) == 1
    assert outbox.read(SESSION, FORECAST)["status"] == "IN_FLIGHT_UNCERTAIN"
    assert outbox.read(SESSION, FORECAST)["claimId"] == claim["claimId"]
    assert outbox.claim(SESSION, FORECAST) is None


def test_crash_after_claim_is_restart_safe(pipeline):
    _journal, outbox, factory, clock = pipeline
    first = outbox.claim(SESSION, FORECAST)
    restarted = ForecastAlertOutbox(factory, lambda: clock[0])
    assert restarted.read(SESSION, FORECAST)["claimId"] == first["claimId"]
    assert restarted.claim(SESSION, FORECAST) is None
    assert restarted.queue(SESSION, FEED, FORECAST) is False


def test_expiry_prevents_new_claim_or_render(pipeline):
    journal, outbox, _factory, clock = pipeline
    clock[0] = 300  # horizon-3 target candle ends at 300
    assert outbox.read(SESSION, FORECAST)["status"] == "EXPIRED_UNCLAIMED"
    assert outbox.claim(SESSION, FORECAST) is None
    with pytest.raises(ValueError):
        render(journal, outbox, clock)


@pytest.mark.parametrize("claim_first", [False, True])
def test_intervening_gap_invalidates_review_even_if_already_claimed(
        pipeline, claim_first):
    journal, outbox, _factory, clock = pipeline
    if claim_first:
        assert outbox.claim(SESSION, FORECAST) is not None
    clock[0] = 240
    # Start 180 skips expected start 120; journal voids prospective forecast.
    assert journal.append(SESSION, FEED, 120, 2,
                          {"kind": "CANDLE", "start": 180, "close": 101.0})
    assert journal.load(SESSION)["forecasts"][0]["status"] == "VOID_GAP"
    with pytest.raises(ValueError):
        render(journal, outbox, clock)
    if claim_first:
        assert outbox.claim(SESSION, FORECAST) is None
    # No fake opener was invoked; invalidation never authorizes an HTTP send.
