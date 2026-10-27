"""Opt-in Telegram Bot API delivery adapter for *review-only* forecast alerts.

Disconnected from routes, schedulers and forecast outbox. Call only after a
separately authenticated feed check and a durable one-time outbox claim. A
provider acceptance is NOT a device delivery receipt. Never retry uncertain
outcomes automatically. No orders or broker API calls exist in this module.
"""
from http.client import HTTPException
import json
import re
import unicodedata
import urllib.error
import urllib.request

_TOKEN = re.compile(r"[0-9]{6,15}:[A-Za-z0-9_-]{20,100}\Z")
_CHAT = re.compile(r"-?[0-9]{1,20}\Z")
_MAX_RESPONSE = 16384
_REVIEW_HEADER = "UNVERIFIED RESEARCH FORECAST - NOT LIVE / NOT A TRADE\n"
_REVIEW_FOOTER = ("Source NOT authenticated; no broker BID/ASK or fill. "
                  "NO BUY/SELL SIGNAL. NO PAPER OR LIVE ORDER.")


class DeliveryUncertain(RuntimeError):
    """Claim remains uncertain; reconcile externally, never blindly retry."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _safe_review_text(text):
    """Reject Unicode formatting that could disguise a research-only warning.

    Also reject lone surrogates before JSON encoding, so they cannot escape as
    unexpected Unicode errors. Ordinary non-ASCII letters and emoji are fine.
    """
    return (type(text) is str and 1 <= len(text) <= 1000 and
            text.startswith(_REVIEW_HEADER) and text.endswith(_REVIEW_FOOTER) and
            all(c in "\n\t" or unicodedata.category(c) not in
                {"Cc", "Cf", "Cs", "Zl", "Zp"} for c in text))


def send_telegram_once(*, bot_token, chat_id, text, timeout=5, opener=None):
    """One HTTP attempt; return provider acceptance metadata, never delivery proof.

    Credentials must come from secret storage. The caller MUST independently
    verify feed entitlement/authenticity, forecast expiry, one-time claim,
    recipient opt-in and account authorization before invoking this function.
    No exception or return value includes the token, text, or raw response.
    """
    if not isinstance(bot_token, str) or not _TOKEN.fullmatch(bot_token):
        raise ValueError("Invalid Telegram bot token shape")
    if not isinstance(chat_id, str) or not _CHAT.fullmatch(chat_id):
        raise ValueError("Invalid Telegram chat ID")
    if not _safe_review_text(text):
        raise ValueError("Invalid review alert text")
    if type(timeout) not in (int, float) or not 1 <= timeout <= 10:
        raise ValueError("Invalid timeout")
    url = "https://api.telegram.org/bot" + bot_token + "/sendMessage"
    body = json.dumps({"chat_id": chat_id, "text": text, "disable_notification": False},
                      separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={
        "Content-Type": "application/json", "Accept": "application/json"
    }, method="POST")
    transport = opener if opener is not None else urllib.request.build_opener(_NoRedirect)
    try:
        with transport.open(request, timeout=timeout) as response:
            if response.status != 200:
                raise DeliveryUncertain("Telegram request outcome uncertain")
            raw = response.read(_MAX_RESPONSE + 1)
        if len(raw) > _MAX_RESPONSE:
            raise DeliveryUncertain("Telegram response exceeds bound")
        data = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        if (type(data) is not dict or data.get("ok") is not True or
                type(data.get("result")) is not dict or
                type(data["result"].get("message_id")) is not int or
                not 0 < data["result"]["message_id"] <= 2**53 - 1 or
                type(data["result"].get("chat")) is not dict or
                type(data["result"]["chat"].get("id")) is not int or
                str(data["result"]["chat"]["id"]) != chat_id or
                type(data["result"].get("text")) is not str or
                data["result"]["text"] != text):
            raise DeliveryUncertain("Telegram acceptance not independently established")
        return {"provider": "telegram", "providerAccepted": True,
                "deliveryVerified": False, "messageId": data["result"]["message_id"],
                "recipientId": chat_id, "retryPermitted": False,
                "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False}
    except (urllib.error.URLError, OSError, HTTPException, UnicodeError,
            ValueError, KeyError, TypeError, OverflowError, RecursionError,
            AttributeError):
        # Even a locally malformed HTTP response or a deeply nested JSON body
        # may arrive *after* Telegram accepted the send. Never retry blindly.
        raise DeliveryUncertain("Telegram delivery outcome uncertain; manual reconciliation required") from None
