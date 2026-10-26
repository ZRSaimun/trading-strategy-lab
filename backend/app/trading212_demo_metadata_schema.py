"""Strict bounded shape check for opt-in Trading 212 DEMO metadata receipts.

Schema consistency is not account authentication, market data, or a rights check.
No network, storage, execution or logging occurs in this module.
"""
from __future__ import annotations

import math
import re

_TICKER = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_TYPES = frozenset({
    "CRYPTOCURRENCY", "ETF", "FOREX", "FUTURES", "INDEX", "STOCK",
    "WARRANT", "CRYPTO", "CVR", "CORPACT",
})


class DemoMetadataSchemaError(ValueError):
    """No private tickers or response bodies are included in failures."""


def _text(value: object, maximum: int = 256) -> bool:
    return (isinstance(value, str) and 1 <= len(value) <= maximum
            and all(ord(ch) >= 32 and ord(ch) != 127 for ch in value))


def validate_demo_metadata_shape(endpoint: str, payload: object) -> int:
    """Validate one broker metadata collection; return count, never the records.

    This does not cross-check workingScheduleId against exchanges because the
    other endpoint's receipt is not present. It cannot prove a complete catalog.
    """
    limits = {"instruments": 50_000, "exchanges": 2_000}
    if (not isinstance(endpoint, str) or endpoint not in limits
            or not isinstance(payload, list) or len(payload) > limits[endpoint]):
        raise DemoMetadataSchemaError("Invalid DEMO metadata collection")
    seen = set()
    for item in payload:
        if not isinstance(item, dict):
            raise DemoMetadataSchemaError("Invalid DEMO metadata entry")
        if endpoint == "instruments":
            ticker = item.get("ticker")
            quantity = item.get("maxOpenQuantity")
            if (not isinstance(ticker, str) or not _TICKER.fullmatch(ticker)
                    or not isinstance(item.get("currencyCode"), str)
                    or not _CURRENCY.fullmatch(item["currencyCode"])
                    or not isinstance(item.get("type"), str)
                    or item["type"] not in _TYPES
                    or type(item.get("workingScheduleId")) is not int
                    or not 0 <= item["workingScheduleId"] <= 2**63 - 1
                    or type(quantity) not in (int, float)
                    or not 0 <= quantity <= 1_000_000_000_000
                    or not math.isfinite(quantity)
                    or type(item.get("extendedHours")) is not bool
                    or not _text(item.get("name"))
                    or not _text(item.get("shortName"))):
                raise DemoMetadataSchemaError("Invalid DEMO instrument metadata")
            identity = ticker
        else:
            identity = item.get("id")
            schedules = item.get("workingSchedules")
            if (type(identity) is not int or not 0 <= identity <= 2**63 - 1
                    or not _text(item.get("name"))
                    or not isinstance(schedules, list) or len(schedules) > 1000
                    or any(not isinstance(s, dict) for s in schedules)):
                raise DemoMetadataSchemaError("Invalid DEMO exchange metadata")
        if identity in seen:
            raise DemoMetadataSchemaError("Duplicate DEMO metadata identity")
        seen.add(identity)
    return len(payload)
