"""Offline deterministic Telegram transport acceptance tests: no network calls."""
import json
import unicodedata
from http.client import IncompleteRead, HTTPException
from io import BytesIO
from urllib.error import HTTPError, URLError

import pytest

from app.forecast_telegram_transport import DeliveryUncertain, send_telegram_once

TOKEN = "123456789:ABCDEFGHIJKLMNOPQRSTUVWX0123456789"
CHAT = "-1001234567890"

REVIEW_HEADER = "UNVERIFIED RESEARCH FORECAST - NOT LIVE / NOT A TRADE\n"
REVIEW_FOOTER = ("Source NOT authenticated; no broker BID/ASK or fill. "
                 "NO BUY/SELL SIGNAL. NO PAPER OR LIVE ORDER.")


def review_text(body="Forecast review only"):
    return REVIEW_HEADER + body + "\n" + REVIEW_FOOTER



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


def accepted(chat=CHAT, mid=55, text=None):
    if text is None:
        text = review_text()
    return json.dumps({"ok": True, "result": {"message_id": mid,
                                              "chat": {"id": int(chat)},
                                              "text": text}}).encode()


def test_acceptance_is_not_delivery():
    fake = FakeOpener(Reply(accepted()))
    result = send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text(), opener=fake)
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
    ("invalid", CHAT, review_text("x"), 5), (TOKEN, "@someone", review_text("x"), 5),
    (TOKEN, CHAT, "", 5), (TOKEN, CHAT, review_text("x" * 1001), 5),
    (TOKEN, CHAT, review_text("x\x00"), 5), (TOKEN, CHAT, review_text("x"), 0),
    (TOKEN, CHAT, review_text("x"), 11), (TOKEN, CHAT, review_text("x"), True),
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
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text("review"), opener=fake)
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
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text("review"), opener=fake)
    assert len(fake.calls) == 1
    assert "secret" not in str(err.value) and TOKEN not in str(err.value)


def test_non_200_is_uncertain():
    fake = FakeOpener(Reply(accepted(), status=202))
    with pytest.raises(DeliveryUncertain):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text("review"), opener=fake)
    assert len(fake.calls) == 1


def test_json_decoder_recursion_failure_is_uncertain(monkeypatch):
    # JSON decoder recursion limits differ by Python version; inject the error
    # deterministically rather than relying on a specific nesting threshold.
    def decoder_failure(*_args, **_kwargs):
        raise RecursionError("secret nested response")

    monkeypatch.setattr("app.forecast_telegram_transport.json.loads", decoder_failure)
    fake = FakeOpener(Reply(accepted()))
    with pytest.raises(DeliveryUncertain, match="manual reconciliation") as err:
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text("review"), opener=fake)
    assert "secret" not in str(err.value) and len(fake.calls) == 1


@pytest.mark.parametrize("reply", [
    object(),  # malformed response context manager
    Reply(b"invalid utf8\xff"),  # malformed HTTP response body
])
def test_malformed_response_object_is_uncertain(reply):
    fake = FakeOpener(reply=reply)
    with pytest.raises(DeliveryUncertain, match="manual reconciliation"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text("review"), opener=fake)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("unsafe", [
    "review\u202eEDART A TON",  # bidirectional override
    "review\u200e",  # directional mark
    "review\u200d",  # zero-width joiner
    "review\ufeff",  # zero-width no-break space
    "review\ud800",  # lone surrogate
    "review\u2028",  # Unicode line separator
    "review\u2029",  # Unicode paragraph separator
    "review\x7f",  # DEL control
    "review\r",  # carriage-return overwrite
    "review\x85",  # next-line control
])
def test_unicode_spoofing_or_malformed_text_rejected_before_network(unsafe):
    fake = FakeOpener(Reply(accepted()))
    with pytest.raises(ValueError, match="Invalid review alert text"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text(unsafe), opener=fake)
    assert fake.calls == []


@pytest.mark.parametrize("safe", [
    "UNVERIFIED RESEARCH - NOT LIVE / NOT A TRADE",
    "Révision sans exécution",
    "Review 🔎",
])
def test_normal_unicode_review_text_is_allowed(safe):
    fake = FakeOpener(Reply(accepted(text=review_text(safe))))
    result = send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=review_text(safe), opener=fake)
    assert result["providerAccepted"] is True
    assert result["deliveryVerified"] is False
    assert len(fake.calls) == 1


@pytest.mark.parametrize("echo", [
    None,  # missing message text
    17,  # wrong type
    "another forecast",
    "Forecast review only ",  # even trailing whitespace must match
    "Forecast review only\\n",  # no canonicalization of the provider echo
])
def test_provider_acceptance_requires_exact_sent_text_echo(echo):
    # A valid chat ID and message ID alone cannot correlate an ACK to this send.
    result = {"message_id": 55, "chat": {"id": int(CHAT)}}
    if echo is not None:
        result["text"] = echo
    fake = FakeOpener(Reply(json.dumps({"ok": True, "result": result}).encode()))
    with pytest.raises(DeliveryUncertain, match="acceptance not independently established"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT,
                           text=review_text(), opener=fake)
    assert len(fake.calls) == 1


def test_unicode_echo_must_match_exact_codepoints():
    sent = review_text("Révision sans exécution")
    # Visually similar NFD reply is not proof the exact request was accepted.
    fake = FakeOpener(Reply(accepted(text=unicodedata.normalize("NFD", sent))))
    with pytest.raises(DeliveryUncertain):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=sent, opener=fake)
    assert len(fake.calls) == 1


@pytest.mark.parametrize("unlabeled", [
    "Forecast review only",
    "UNVERIFIED RESEARCH FORECAST - NOT LIVE / NOT A TRADE",
    "UNVERIFIED RESEARCH FORECAST - NOT LIVE / NOT A TRADE\nBUY NOW",
    review_text().replace("NO BUY/SELL SIGNAL.", "BUY SIGNAL."),
    "  " + review_text(),
    review_text() + " LIVE BUY",
])
def test_review_disclaimer_cannot_be_omitted_or_overwritten(unlabeled):
    fake = FakeOpener(Reply(accepted()))
    with pytest.raises(ValueError, match="Invalid review alert text"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT, text=unlabeled, opener=fake)
    assert fake.calls == []


@pytest.mark.parametrize("message_id", [2**53, 10**80])
def test_provider_message_id_outside_reconciliation_safe_integer_is_uncertain(message_id):
    # The separate delivery-acceptance audit caps messageId at 2**53-1.
    # Do not record a success that the downstream audit must reject.
    fake = FakeOpener(Reply(accepted(mid=message_id)))
    with pytest.raises(DeliveryUncertain, match="acceptance not independently established"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT,
                           text=review_text(), opener=fake)
    assert len(fake.calls) == 1


def test_provider_message_id_at_reconciliation_boundary_is_accepted():
    fake = FakeOpener(Reply(accepted(mid=2**53 - 1)))
    result = send_telegram_once(bot_token=TOKEN, chat_id=CHAT,
                                text=review_text(), opener=fake)
    assert result["messageId"] == 2**53 - 1
    assert result["deliveryVerified"] is False
    assert len(fake.calls) == 1


@pytest.mark.parametrize("provider_chat_id", [
    CHAT, float(int(CHAT)), True, None,
])
def test_provider_chat_identity_must_be_numeric_integer(provider_chat_id):
    # A JSON string matching chat_id was previously accepted via str(...).
    # The Bot API documents chat.id as an integer, not a string/float/bool.
    response = {"ok": True, "result": {
        "message_id": 55, "chat": {"id": provider_chat_id},
        "text": review_text()}}
    fake = FakeOpener(Reply(json.dumps(response).encode("utf-8")))
    with pytest.raises(DeliveryUncertain, match="acceptance not independently established"):
        send_telegram_once(bot_token=TOKEN, chat_id=CHAT,
                           text=review_text(), opener=fake)
    assert len(fake.calls) == 1
