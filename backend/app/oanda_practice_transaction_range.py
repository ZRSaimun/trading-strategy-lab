"""Bounded, GET-only OANDA v20 practice transaction-ID-range evidence preflight.

This optional adapter companion has no order methods, persistence, or brokerage
side effects. A validated response is not authenticated statement completeness.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

_ID = re.compile(r"(?:0|[1-9][0-9]{0,19})\Z")
_ACCOUNT = re.compile(r"[0-9]{3}-[0-9]{3}-[0-9]{4,12}-[0-9]{3}\Z")
_TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,9})?Z\Z")
_TYPE = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
_MAX_RANGE = 100


def _id(value):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("Invalid practice transaction ID")
    return int(value)


def _nanoseconds(value):
    if type(value) is not str or _TIMESTAMP.fullmatch(value) is None:
        raise ValueError("Invalid practice transaction timestamp")
    try:
        at = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid practice transaction timestamp") from exc
    frac = value.partition(".")[2].removesuffix("Z")
    epoch_delta = at - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return ((epoch_delta.days * 86400 + epoch_delta.seconds) * 1_000_000_000
            + int((frac + "000000000")[:9]))


def validate_practice_transaction_range(response, *, account_id, first_id, last_id, as_of):
    """Validate a caller-supplied native idrange response without trusting it.

    Returns redacted evidence only. Missing IDs are explicitly exposed, and
    no result can be used as proof of complete/authentic broker history.
    """
    if type(account_id) is not str or _ACCOUNT.fullmatch(account_id) is None:
        raise ValueError("Invalid practice account identity")
    start, end = _id(first_id), _id(last_id)
    if start < 1 or end < start or end - start >= _MAX_RANGE:
        raise ValueError("Unbounded or reversed transaction range")
    if (not isinstance(as_of, datetime) or as_of.tzinfo is None or
            as_of.utcoffset() is None):
        raise ValueError("Explicit timezone-aware cutoff required")
    cutoff = as_of.astimezone(timezone.utc)
    cutoff_delta = cutoff - datetime(1970, 1, 1, tzinfo=timezone.utc)
    cutoff_ns = ((cutoff_delta.days * 86400 + cutoff_delta.seconds) * 1_000_000_000
                 + cutoff.microsecond * 1000)
    if type(response) is not dict or set(response) != {"transactions", "lastTransactionID"}:
        raise ValueError("Unexpected practice transaction response schema")
    cursor = _id(response["lastTransactionID"])
    if cursor < end:
        raise ValueError("Practice transaction cursor behind requested range")
    rows = response["transactions"]
    if type(rows) is not list or len(rows) > end - start + 1:
        raise ValueError("Invalid practice transaction population")
    seen, prev_id, prev_time = [], start - 1, -1
    types = {}
    for row in rows:
        if type(row) is not dict or row.get("accountID") != account_id:
            raise ValueError("Cross-account or malformed practice transaction")
        transaction_id = _id(row.get("id"))
        if transaction_id <= prev_id or not start <= transaction_id <= end:
            raise ValueError("Duplicate, unsorted or out-of-range practice transaction")
        event_type = row.get("type")
        if type(event_type) is not str or _TYPE.fullmatch(event_type) is None:
            raise ValueError("Invalid practice transaction type")
        timestamp = _nanoseconds(row.get("time"))
        if timestamp > cutoff_ns or timestamp < prev_time:
            raise ValueError("Future or retrograde practice transaction time")
        seen.append(transaction_id)
        types[event_type] = types.get(event_type, 0) + 1
        prev_id, prev_time = transaction_id, timestamp
    contiguous = seen == list(range(start, end + 1))
    # Canonicalized response identity is not a broker signature or raw-byte hash.
    try:
        canonical = json.dumps(response, sort_keys=True, separators=(",", ":"),
                               ensure_ascii=True, allow_nan=False).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("Non-JSON practice transaction evidence") from exc
    digest = hashlib.sha256(canonical).hexdigest()
    return {"provider": "OANDA_V20_PRACTICE", "account_id": account_id,
            "requested_first_id": first_id, "requested_last_id": last_id,
            "broker_reported_latest_id": response["lastTransactionID"],
            "observed_ids": [str(value) for value in seen],
            "observed_count": len(seen), "missing_id_count": end - start + 1 - len(seen),
            "observed_contiguous_id_range": contiguous,
            "observed_type_counts": dict(sorted(types.items())),
            "canonical_response_sha256": digest,
            "original_response_bytes_authenticated": False,
            "complete_broker_history_authenticated": False,
            "cash_ledger_reconciled": False,
            "may_execute_demo_order": False, "may_execute_real_order": False}


def read_practice_transaction_range(adapter, first_id, last_id, *, as_of):
    """One bounded GET via an opt-in OandaPracticeReadOnly adapter.

    The existing adapter's `_get` enforces the practice host, disabled default,
    timeout, no redirects, no environment proxy and a 256-KiB response ceiling.
    """
    # Validate all caller inputs *before* any possible network request.
    account = getattr(adapter, "_account", None)
    if type(account) is not str or _ACCOUNT.fullmatch(account) is None:
        raise ValueError("Invalid practice account identity")
    start, end = _id(first_id), _id(last_id)
    if start < 1 or end < start or end - start >= _MAX_RANGE:
        raise ValueError("Unbounded or reversed transaction range")
    if not isinstance(as_of, datetime) or as_of.tzinfo is None or as_of.utcoffset() is None:
        raise ValueError("Explicit timezone-aware cutoff required")
    # The only network path this function can request is a literal GET idrange.
    response = adapter._get("/transactions/idrange", {"from": first_id, "to": last_id})
    return validate_practice_transaction_range(response, account_id=account,
                                               first_id=first_id, last_id=last_id,
                                               as_of=as_of)
