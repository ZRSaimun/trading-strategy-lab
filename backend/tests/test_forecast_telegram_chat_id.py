"""Offline shared recipient-identity boundary tests (no Telegram requests)."""
import pytest
from app.forecast_telegram_chat_id import valid_telegram_chat_id


@pytest.mark.parametrize("chat_id", [
    "1", "-1", "-1001234567890", "-4000000000000", "1099511627775",
])
def test_valid_canonical_chat_ids(chat_id):
    assert valid_telegram_chat_id(chat_id) is True


@pytest.mark.parametrize("chat_id", [
    "0", "-0", "00", "000123", "-00123", "+123", " 123", "123 ",
    "-4000000000001", "1099511627776", "111111111111111111111", "1.0",
    "@channel", "", "１２３", 123, True, None, 1.0, [], {},
])
def test_noncanonical_or_out_of_range_chat_ids(chat_id):
    assert valid_telegram_chat_id(chat_id) is False
