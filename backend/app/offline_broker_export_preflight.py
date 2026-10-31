"""Read-only, fail-closed preflight for a *normalized* broker export CSV.

No provider-specific parser, network access, orders, credentials, source
authentication, financing inference, or assertion of statement completeness.
A digest supplied with the bytes is only a consistency check.
"""
from __future__ import annotations

import csv
from decimal import Decimal
import hashlib
import io
import re

_PROTOCOL = "normalized-broker-export-preflight-v1"
_COLUMNS = (
    "sequence", "event_id", "kind", "provider", "venue", "account_alias",
    "instrument", "position_id", "order_id", "currency", "source_ref",
    "effective_at_ms", "posted_at_ms", "side", "quantity", "price", "signed_cash",
)
_SCOPE = frozenset({
    "provider", "venue", "account_alias", "currency", "export_id",
    "captured_at_ms", "evaluation_as_of_ms", "expected_sha256", "expected_event_count",
})
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_POSITIVE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?\Z")
_KINDS = frozenset({"FILL", "COMMISSION", "FINANCING", "ADJUSTMENT"})
_MAX_BYTES = 2_000_000
_MAX_EVENTS = 5_000
_MAX_MS = 100_000_000_000_000


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_MS


def _number(value, *, cash=False):
    pattern = _CASH if cash else _POSITIVE
    if type(value) is not str or not pattern.fullmatch(value):
        raise ValueError("Invalid bounded exact decimal")
    if cash and value.startswith("-") and Decimal(value) == 0:
        raise ValueError("Negative zero is not a canonical cash amount")
    amount = Decimal(value)
    if not cash and amount <= 0:
        raise ValueError("Quantity and price must be positive")
    return amount


def _row_clock(value):
    if type(value) is not str or not re.fullmatch(r"(?:0|[1-9][0-9]{0,14})", value):
        raise ValueError("Invalid event timestamp")
    number = int(value)
    if not _clock(number):
        raise ValueError("Event timestamp out of bounds")
    return number


def preflight_normalized_broker_export(scope, raw_csv):
    """Validate one normalized, source-isolated, point-in-time CSV snapshot.

    A separate, authenticated provider adapter must transform an actual export
    into this canonical schema and prove completeness/custody externally.
    Returned event dictionaries are untrusted declarations, not broker receipts.
    """
    if type(scope) is not dict or set(scope) != _SCOPE:
        raise ValueError("Invalid exact export scope")
    if not all(_id(scope[k]) for k in ("provider", "venue", "account_alias", "export_id")):
        raise ValueError("Invalid export identity")
    if type(scope["currency"]) is not str or not re.fullmatch(r"[A-Z]{3}", scope["currency"]):
        raise ValueError("Invalid settlement currency")
    captured, as_of = scope["captured_at_ms"], scope["evaluation_as_of_ms"]
    if not _clock(captured) or not _clock(as_of) or captured > as_of:
        raise ValueError("Export not available at evaluation cutoff")
    count = scope["expected_event_count"]
    if type(count) is not int or not 1 <= count <= _MAX_EVENTS:
        raise ValueError("Expected population must be nonempty and bounded")
    digest = scope["expected_sha256"]
    if type(digest) is not str or not _SHA.fullmatch(digest):
        raise ValueError("Invalid expected export digest")
    if type(raw_csv) is not bytes or not 0 < len(raw_csv) <= _MAX_BYTES:
        raise ValueError("Export bytes missing or oversized")
    if hashlib.sha256(raw_csv).hexdigest() != digest:
        raise ValueError("Original export bytes differ from declared digest")
    try:
        content = raw_csv.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid UTF-8 normalized export") from exc
    if "\ufeff" in content or "\x00" in content:
        raise ValueError("BOM or NUL not permitted in canonical export")
    if raw_csv.count(b"\n") > _MAX_EVENTS + 1:
        raise ValueError("Unbounded physical CSV lines")
    try:
        reader = csv.reader(io.StringIO(content, newline=""), strict=True)
        header = next(reader, None)
        if header != list(_COLUMNS) or reader.line_num != 1:
            raise ValueError("Unexpected normalized export column order")
        events = []
        totals = {kind: Decimal(0) for kind in sorted(_KINDS - {"FILL"})}
        counts = {kind: 0 for kind in sorted(_KINDS)}
        ids = set()
        previous_posted = -1
        for row in reader:
            if reader.line_num != len(events) + 2 or len(row) != len(_COLUMNS):
                raise ValueError("Malformed, multiline or blank CSV record")
            if len(events) >= count or any(len(cell) > 160 for cell in row):
                raise ValueError("Unbounded or unexpected event population")
            event = dict(zip(_COLUMNS, row))
            sequence = event["sequence"]
            if sequence != str(len(events) + 1):
                raise ValueError("Missing, duplicated or out-of-order event sequence")
            if (not _id(event["event_id"]) or event["event_id"] in ids or
                not _id(event["instrument"]) or not _id(event["position_id"]) or
                not _id(event["source_ref"]) or
                (event["order_id"] != "" and not _id(event["order_id"]))):
                raise ValueError("Invalid or duplicated event identity")
            if (event["provider"] != scope["provider"] or
                event["venue"] != scope["venue"] or
                event["account_alias"] != scope["account_alias"] or
                event["currency"] != scope["currency"]):
                raise ValueError("Mixed-source or mixed-currency export")
            kind = event["kind"]
            if kind not in _KINDS:
                raise ValueError("Unsupported normalized event kind")
            effective = _row_clock(event["effective_at_ms"])
            posted = _row_clock(event["posted_at_ms"])
            if not effective <= posted <= captured or posted < previous_posted:
                raise ValueError("Future, impossible or retroactively reordered event")
            if kind == "FILL":
                if (not _id(event["order_id"]) or event["side"] not in ("BUY", "SELL")
                        or event["signed_cash"] != ""):
                    raise ValueError("Malformed normalized fill")
                _number(event["quantity"])
                _number(event["price"])
            else:
                if (event["side"] != "" or event["quantity"] != "" or
                        event["price"] != ""):
                    raise ValueError("Cash posting cannot masquerade as a fill")
                totals[kind] += _number(event["signed_cash"], cash=True)
            counts[kind] += 1
            ids.add(event["event_id"])
            previous_posted = posted
            events.append(event)
    except csv.Error as exc:
        raise ValueError("Malformed normalized CSV syntax") from exc
    if len(events) != count:
        raise ValueError("Declared event population does not match CSV")
    return {
        "protocol": _PROTOCOL,
        "status": "DECLARED_NORMALIZED_EXPORT_ONLY",
        "source_identity": {k: scope[k] for k in ("provider", "venue", "account_alias", "currency", "export_id")},
        "captured_at_ms": captured,
        "evaluation_as_of_ms": as_of,
        "original_csv_sha256": digest,
        "event_count": count,
        "kind_counts": counts,
        "declared_cash_by_kind": {k: str(v) for k, v in totals.items()},
        "events": events,
        "authenticated_broker_source": False,
        "independent_statement_completeness": False,
        "verified_cfd_financing_calendar": False,
        "verified_profitability": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "Normalized caller-supplied bytes and self-declared population only; no authenticated broker statement, external completeness proof, FX settlement, P&L or trading permission.",
    }
