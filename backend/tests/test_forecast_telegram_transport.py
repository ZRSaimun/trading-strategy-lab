"""Offline deterministic Telegram transport acceptance tests: no network calls."""
import json
from http.client import IncompleteRead, HTTPException
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from app.forecast_telegram_transport import DeliveryUncertain, send_telegram_once

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWX0123456789"
CHAT = "-1001234567890"


class Reply:
    def __init__(self, payload, status=200):
        self.status = status
        self.payload = BytesIO(payload)

    def read(self, size):
        return self.payload.read(size)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


class FakeOpener:
    def __init__(self, reply=None, error=None):
        self.reply = reply
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append((request, timeout))
        if self.error:
            raise self.error
        return self.reply


def accepted(chat=CHAT, mid=55):
    return json.dumps({"ok": True, "result": {"message_id": mid,
                                              "chat": {"id": int(chat)}}}).encode()


def test_acceptance_is_not_delivery():
    fake = FakeOpener(Reply(accepted()))
    result = send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text="Forecast review only", opener=fake)
    assert result == {"provider": "telegram", "providerAccepted": True,
                      "deliveryVerified": False, "messageId": 55, "recipientId": CHAT,
                      "retryPermitted": False, "mayExecutePaperOrder": False,
                      "mayExecuteLiveOrder": False}
    assert len(fake.calls) == 1
    request, timeout = fake.calls[0]
    assert request.full_url.startswith("https://api.telegram.org/bot")
    assert request.get_method() == "POST" and timeout == 5
    assert json.loads(request.data)["chat_id"] == CHAT
    assert "parse_mode" not in json.loads(request.data)


@pytest.mark.parametrize("token,chat,text,timeout", [
    ("invalid", CHAT, "x", 5), (TOKEN, "@someone", "x", 5),
    (TOKEN, CHAT, "", 5), (TOKEN, CHAT, "x" * 1001, 5),
    (TOKEN, CHAT, "x\x00", 5), (TOKEN, CHAT, "x", 0),
    (TOKEN, CHAT, "x", 11), (TOKEN, CHAT, "x", True),
])
def test_invalid_arguments_never_call_network(token, chat, text, timeout):
    fake = FakeOpener(Reply(accepted()))
    with pytest.raises(ValueError):
        send_telegram_once(bot_token=token, chat_id=chat, text=text,
                           timeout=timeout, opener=fake)
    assert fake.calls == []


@pytest.mark.parametrize("payload", [
    b"{}", b'{"ok":false}', b'{"ok":true}',
    b'{"ok":true,"result":{"message_id":55,"chat":{"id":1}}}',
    b'{"ok":true,"result":{"message_id":true,"chat":{"id":-1001234567890}}}',
    b'{"ok":true,"result":{"message_id":0,"chat":{"id":-1001234567890}}}',
    b'{"ok":true,"ok":true,"result":{"message_id":55,"chat":{"id":-1001234567890}}}',
    b"not-json", b"x" * 16385,
])
def test_untrusted_response_fails_closed(payload):
    fake = FakeOpener(Reply(payload))
    with pytest.raises(DeliveryUncertain) as err:
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text="review", opener=fake)
    assert TOKEN not in str(err.value) and len(fake.calls) == 1


@pytest.mark.parametrize("failure", [
    URLError("secret token:123456"), TimeoutError("secret timeout"),
    HTTPError("https://api.telegram.org/secret", 302, "redirect", {}, None),
    IncompleteRead(b"secret partial body", 99),
    HTTPException("secret HTTP framing failure"),
])
def test_network_failures_never_expose_secret_or_retry(failure):
    fake = FakeOpener(error=failure)
    with pytest.raises(DeliveryUncertain) as err:
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text="review", opener=fake)
    assert len(fake.calls) == 1
    assert "secret" not in str(err.value) and TOKEN not in str(err.value)


def test_non_200_is_uncertain():
    fake = FakeOpener(Reply(accepted(), status=202))
    with pytest.raises(DeliveryUncertain):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text="review", opener=fake)
    assert len(fake.calls) == 1


def test_json_decoder_recursion_failure_is_uncertain(monkeypatch):
    # JSON decoder recursion limits differ by Python version; inject the error
    # deterministically rather than relying on a specific nesting threshold.
    def decoder_failure(*_args, **_kwargs):
        raise RecursionError("secret nested response")

    monkeypatch.setattr("app.forecast_telegram_transport.json.loads", decoder_failure)
    fake = FakeOpener(Reply(accepted()))
    with pytest.raises(DeliveryUncertain, match="manual reconciliation") as err:
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text="review", opener=fake)
    assert "secret" not in str(err.value) and len(fake.calls) == 1


@pytest.mark.parametrize("reply", [
    object(),  # malformed response context manager
    Reply(b"invalid utf8\xff"),  # malformed HTTP response body
])
def test_malformed_response_object_is_uncertain(reply):
    fake = FakeOpener(reply=reply)
    with pytest.raises(DeliveryUncertain, match="manual reconciliation"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text="review", opener=fake)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("unsafe", [
    "review\\u202eEDART A TON",  # bidirectional override
    "review\\u200e",  # directional mark
    "review\\u200d",  # zero-width joiner
    "review\\ufeff",  # zero-width no-break space
    "review\\ud800",  # lone surrogate
    "review\\u2028",  # Unicode line separator
    "review\\u2029",  # Unicode paragraph separator
    "review\\x7f",  # DEL control
    "review\\r",  # carriage-return overwrite
    "review\\x85",  # next-line control
])
def test_unicode_spoofing_or_malformed_text_rejected_before_network(unsafe):
    fake = FakeOpener(Reply(accepted()))
    with pytest.raises(ValueError, match="Invalid review alert text"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=unsafe, opener=fake)
    assert fake.calls == []


@pytest.mark.parametrize("safe", [
    "UNVERIFIED RESEARCH - NOT LIVE / NOT A TRADE",
    "Révision sans exécution",
    "Review 🔎",
])
def test_normal_unicode_review_text_is_allowed(safe):
    fake = FakeOpener(Reply(accepted()))
    result = send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=safe, opener=fake)
    assert result["providerAccepted"] is True
    assert result["deliveryVerified"] is False
    assert len(fake.calls) == 1
