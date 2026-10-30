"""Disconnected, read-only reconciliation of Trading 212 equity metadata receipts.

Only compares caller-supplied results from the opt-in read-only adapter. It
cannot authenticate account identity, licensing, venue schedules or prices.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
import math
import re

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TICKER = re.compile(r"[A-Za-z0-9_.:-]{1,96}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_TYPES = frozenset({
    "CRYPTOCURRENCY", "ETF", "FOREX", "FUTURES", "INDEX", "STOCK",
    "WARRANT", "CRYPTO", "CVR", "CORPACT",
})
_MAX_INSTRUMENTS = 50_000
_MAX_EXCHANGES = 2_000
_MAX_LOOKUPS = 25


class InstrumentCatalogError(ValueError):
    """Sanitized metadata rejection; never includes private response bodies."""


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or len(value) > 40:
        raise InstrumentCatalogError("Invalid receipt time")
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise InstrumentCatalogError("Invalid receipt time") from None
    if stamp.tzinfo is None or stamp.utcoffset() != timedelta(0):
        raise InstrumentCatalogError("UTC receipt time required")
    return stamp


def _text(value: object, *, maximum: int = 256) -> str:
    if (not isinstance(value, str) or not 1 <= len(value) <= maximum
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise InstrumentCatalogError("Invalid metadata text")
    return value


def _receipt(receipt: object, endpoint: str) -> tuple[dict, datetime]:
    if not isinstance(receipt, dict):
        raise InstrumentCatalogError("Invalid broker receipt")
    if (receipt.get("provider") != "Trading 212" or receipt.get("endpoint") != endpoint
            or receipt.get("environment") not in ("DEMO", "LIVE")
            or receipt.get("account_type_declared") not in ("INVEST", "STOCKS_ISA")
            or receipt.get("account_type_verified") is not False
            or receipt.get("market_data_feed") is not False
            or receipt.get("cfd_supported") is not False
            or receipt.get("may_execute_order") is not False
            or receipt.get("server_clock_attested") is not False
            or not isinstance(receipt.get("response_sha256"), str)
            or not _SHA.fullmatch(receipt["response_sha256"])):
        raise InstrumentCatalogError("Invalid or overstated broker receipt provenance")
    return receipt, _utc(receipt.get("received_at_utc"))


def reconcile_trading212_instrument_catalog(
    instruments_receipt: dict, exchanges_receipt: dict, *,
    declared_account_scope_sha256: str, requested_tickers: list[str] | None = None,
) -> dict:
    """Reconcile bounded equity instrument/exchange metadata; never query broker.

    A matching declared account scope is an operator assertion, not an account
    proof. Return only selected, non-price metadata and aggregate fingerprints.
    """
    if (not isinstance(declared_account_scope_sha256, str)
            or not _SHA.fullmatch(declared_account_scope_sha256)):
        raise InstrumentCatalogError("Declared account scope fingerprint required")
    inst, inst_at = _receipt(instruments_receipt, "instruments")
    exch, exch_at = _receipt(exchanges_receipt, "exchanges")
    if (inst["environment"] != exch["environment"]
            or inst["account_type_declared"] != exch["account_type_declared"]
            or abs((inst_at - exch_at).total_seconds()) > 600):
        raise InstrumentCatalogError("Incompatible or distant metadata receipts")
    lookups = [] if requested_tickers is None else requested_tickers
    if (not isinstance(lookups, list) or len(lookups) > _MAX_LOOKUPS
            or any(not isinstance(t, str) or not _TICKER.fullmatch(t) for t in lookups)
            or len(set(lookups)) != len(lookups)):
        raise InstrumentCatalogError("Invalid selected ticker population")
    instruments, exchanges = inst.get("data"), exch.get("data")
    if (not isinstance(instruments, list) or not 1 <= len(instruments) <= _MAX_INSTRUMENTS
            or not isinstance(exchanges, list) or not 1 <= len(exchanges) <= _MAX_EXCHANGES):
        raise InstrumentCatalogError("Invalid metadata population")
    exchange_ids = {}
    # workingScheduleId points to nested WorkingSchedule.id, NOT Exchange.id.
    # Keep this declared linkage separate from any verified trading calendar.
    schedule_to_exchange = {}
    canonical_exchanges = []
    for item in exchanges:
        if not isinstance(item, dict):
            raise InstrumentCatalogError("Invalid exchange entry")
        ident = item.get("id")
        if type(ident) is not int or not 0 <= ident <= 2**63 - 1 or ident in exchange_ids:
            raise InstrumentCatalogError("Invalid or duplicate exchange identifier")
        name = _text(item.get("name"))
        schedules = item.get("workingSchedules")
        if not isinstance(schedules, list) or len(schedules) > 1000:
            raise InstrumentCatalogError("Invalid exchange schedule collection")
        normalized_schedules = []
        for entry in schedules:
            if not isinstance(entry, dict):
                raise InstrumentCatalogError("Invalid working schedule entry")
            schedule_id, events = entry.get("id"), entry.get("timeEvents")
            if (type(schedule_id) is not int or not 0 <= schedule_id <= 2**63 - 1
                    or schedule_id in schedule_to_exchange
                    or not isinstance(events, list) or len(events) > 10_000):
                raise InstrumentCatalogError("Invalid or duplicate working schedule")
            schedule_to_exchange[schedule_id] = (ident, name)
            normalized_schedules.append(entry)
        # Schedule ordering is not a catalog change. Event contents remain
        # opaque fingerprinted metadata, not verified open-market evidence.
        normalized_schedules.sort(key=lambda entry: entry["id"])
        exchange_ids[ident] = name
        canonical_exchanges.append([ident, name, normalized_schedules])
    by_ticker = {}
    types = Counter()
    canonical = []
    for item in instruments:
        if not isinstance(item, dict):
            raise InstrumentCatalogError("Invalid instrument entry")
        ticker = item.get("ticker")
        currency = item.get("currencyCode")
        kind = item.get("type")
        schedule = item.get("workingScheduleId")
        quantity = item.get("maxOpenQuantity")
        if (not isinstance(ticker, str) or not _TICKER.fullmatch(ticker)
                or ticker in by_ticker or not isinstance(currency, str)
                or not _CURRENCY.fullmatch(currency)
                or not isinstance(kind, str) or kind not in _TYPES
                or type(schedule) is not int or schedule not in schedule_to_exchange
                or type(quantity) not in (int, float) or not math.isfinite(quantity)
                or not 0 <= quantity <= 1_000_000_000_000
                or type(item.get("extendedHours")) is not bool):
            raise InstrumentCatalogError("Invalid, duplicate or unlinked instrument metadata")
        name = _text(item.get("name"))
        short_name = _text(item.get("shortName"))
        # Metadata names and schedules are descriptive only; no market-hours
        # interpretation, trade eligibility, price or liquidity inference.
        exchange_id, exchange_name = schedule_to_exchange[schedule]
        record = {"ticker": ticker, "type": kind, "currency": currency,
                  "exchange_id": exchange_id, "exchange_name": exchange_name,
                  "working_schedule_id": schedule, "name": name}
        by_ticker[ticker] = record
        types[kind] += 1
        canonical.append([ticker, kind, currency, schedule, exchange_id, name, short_name,
                          item["extendedHours"], quantity])
    canonical.sort(key=lambda item: item[0])
    canonical_exchanges.sort(key=lambda item: item[0])
    try:
        canonical_bytes = json.dumps([canonical, canonical_exchanges],
                            sort_keys=True, ensure_ascii=True, allow_nan=False,
                            separators=(",", ":")).encode("utf-8")
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise InstrumentCatalogError("Invalid nested schedule metadata") from None
    digest = hashlib.sha256(canonical_bytes).hexdigest()
    return {
        "status": "DECLARED_EQUITY_METADATA_RECONCILED_UNVERIFIED",
        "provider": "Trading 212", "environment": inst["environment"],
        "account_type_declared": inst["account_type_declared"],
        "instruments_count": len(instruments), "exchanges_count": len(exchanges),
        "instrument_types": dict(sorted(types.items())),
        "catalog_sha256": digest,
        "requested": [by_ticker[t] for t in lookups if t in by_ticker],
        "not_found": [t for t in lookups if t not in by_ticker],
        "same_account_verified": False, "provider_entitlement_verified": False,
        "market_calendar_verified": False, "metadata_freshness_verified": False,
        "market_data_feed": False, "price_freshness_verified": False,
        "cfd_supported": False, "may_execute_order": False,
    }
