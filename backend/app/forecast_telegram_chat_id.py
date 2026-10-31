"""Shared canonical Telegram numeric chat-ID preflight for disconnected audits.

Syntactic validation only. It does not establish consent, account ownership,
provider existence, delivery, or authority to send an alert.
"""
import re

_CHAT = re.compile(r"-?[0-9]{1,20}\Z")
_MIN_CHAT_ID = -4_000_000_000_000
_MAX_CHAT_ID = 1_099_511_627_775


def valid_telegram_chat_id(value):
    """Match the sender's canonical numeric Bot API chat-ID contract."""
    if type(value) is not str or _CHAT.fullmatch(value) is None:
        return False
    numeric = int(value)
    return (numeric != 0 and str(numeric) == value and
            _MIN_CHAT_ID <= numeric <= _MAX_CHAT_ID)
