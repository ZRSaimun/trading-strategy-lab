"""Offline continuity audit for two caller-declared normalized broker exports.

Never authenticates a broker, verifies completeness, or permits order routing.
A late-posted correction is retained and explicitly withholds earlier completeness.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

_PROTOCOL = "declared-broker-export-continuity-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_MONEY = re.compile(r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,2})?\Z")
_QTY = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_SOURCE = {"provider", "venue", "account_alias", "settlement_currency"}
_SNAPSHOT = {"source", "snapshot_id", "statement_sha256", "coverage_start", "coverage_end", "exported_at", "ingested_at", "events"}
_EVENT = {"event_id", "kind", "instrument", "position_id", "side", "occurred_at", "recorded_at", "quantity", "cash_amount", "revision", "supersedes_id", "evidence_sha256"}
_CASH_KINDS = ("COMMISSION", "FINANCING", "ADJUSTMENT")
_MAX_TIME = 8640000000
_MAX_EVENTS = 5000


def _exact(value, keys, name):
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"Invalid {name} schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _decimal(value, pattern, name):
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError(f"Invalid {name} decimal")
    number = Decimal(value)
    if number.is_zero() and value.startswith("-"):
        raise ValueError(f"Negative-zero {name} decimal")
    return number


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _validate(snapshot):
    _exact(snapshot, _SNAPSHOT, "broker export snapshot")
    source = snapshot["source"]
    _exact(source, _SOURCE, "broker export source")
    if not all(_id(source[k]) for k in ("provider", "venue", "account_alias")) or (
        type(source["settlement_currency"]) is not str or
        _CURRENCY.fullmatch(source["settlement_currency"]) is None
    ):
        raise ValueError("Invalid broker source identity")
    if not _id(snapshot["snapshot_id"]) or not _sha(snapshot["statement_sha256"]):
        raise ValueError("Invalid export snapshot identity")
    start, end = snapshot["coverage_start"], snapshot["coverage_end"]
    exported, ingested = snapshot["exported_at"], snapshot["ingested_at"]
    if not all(_clock(t) for t in (start, end, exported, ingested)) or not (
        start < end <= exported <= ingested
    ):
        raise ValueError("Invalid export coverage or availability clocks")
    events = snapshot["events"]
    if type(events) is not list or len(events) > _MAX_EVENTS:
        raise ValueError("Unbounded broker event population")
    by_id = {}
    children = set()
    for row in events:
        _exact(row, _EVENT, "normalized broker event")
        event_id = row["event_id"]
        if not _id(event_id) or event_id in by_id:
            raise ValueError("Invalid or duplicate event ID")
        if not _id(row["instrument"]) or not _id(row["position_id"]) or not _sha(row["evidence_sha256"]):
            raise ValueError("Invalid event source identity")
        if row["kind"] not in ("FILL",) + _CASH_KINDS:
            raise ValueError("Unsupported normalized event kind")
        if not all(_clock(row[k]) for k in ("occurred_at", "recorded_at")) or not (
            start <= row["occurred_at"] <= end and
            row["occurred_at"] <= row["recorded_at"] <= exported
        ):
            raise ValueError("Invalid event chronology")
        if type(row["revision"]) is not int or not 1 <= row["revision"] <= 100:
            raise ValueError("Invalid event revision")
        predecessor = row["supersedes_id"]
        if predecessor is not None and (not _id(predecessor) or predecessor == event_id or predecessor in children):
            raise ValueError("Invalid or forked event correction")
        if predecessor is not None:
            children.add(predecessor)
        qty = _decimal(row["quantity"], _QTY, "quantity")
        cash = _decimal(row["cash_amount"], _MONEY, "cash")
        if row["kind"] == "FILL":
            if row["side"] not in ("BUY", "SELL") or qty <= 0 or cash != 0:
                raise ValueError("Invalid fill fields")
        elif row["side"] != "NONE" or qty != 0:
            raise ValueError("Invalid cash-only event fields")
        by_id[event_id] = row
    for row in events:
        predecessor = row["supersedes_id"]
        if predecessor is None:
            if row["revision"] != 1:
                raise ValueError("Revision without predecessor")
            continue
        old = by_id.get(predecessor)
        if old is None:
            raise ValueError("Correction references absent predecessor")
        if (row["revision"] != old["revision"] + 1 or
            row["recorded_at"] <= old["recorded_at"] or
            any(row[k] != old[k] for k in ("kind", "instrument", "position_id", "side", "occurred_at"))):
            raise ValueError("Inconsistent correction lineage or availability")
    return by_id, children


def _effective_cash(by_id, superseded):
    with localcontext() as ctx:
        ctx.prec = 64
        totals = {kind: Decimal(0) for kind in _CASH_KINDS}
        for event_id, row in by_id.items():
            if event_id not in superseded and row["kind"] in totals:
                totals[row["kind"]] += Decimal(row["cash_amount"])
        return {kind: format(totals[kind].quantize(Decimal("0.01")), ".2f") for kind in _CASH_KINDS}


def audit_broker_export_snapshot_continuity(earlier, later):
    """Check append-only event continuity across two self-declared exports.

    A newly observed late-posted historical event is permitted but prevents
    any assertion that the earlier event population was complete. Event changes
    and undocumented historical backfills fail closed. No P&L is calculated.
    """
    old, old_superseded = _validate(earlier)
    new, new_superseded = _validate(later)
    if earlier["source"] != later["source"]:
        raise ValueError("Cross-source export comparison")
    if (earlier["snapshot_id"] == later["snapshot_id"] or
        earlier["coverage_start"] != later["coverage_start"] or
        later["coverage_end"] < earlier["coverage_end"] or
        later["exported_at"] <= earlier["exported_at"] or
        later["ingested_at"] < earlier["ingested_at"]):
        raise ValueError("Regressed or reused export snapshot chronology")
    if not set(old).issubset(new):
        raise ValueError("Historical event missing from later export")
    for event_id, row in old.items():
        if new[event_id] != row:
            raise ValueError("Historical event was rewritten")
    added = sorted(set(new) - set(old))
    if earlier["statement_sha256"] == later["statement_sha256"] and added:
        raise ValueError("Same declared statement bytes cannot contain additional events")
    late = []
    corrections = []
    for event_id in added:
        row = new[event_id]
        if row["occurred_at"] <= earlier["coverage_end"]:
            if row["recorded_at"] <= earlier["exported_at"]:
                raise ValueError("Retroactive event omitted despite prior recorded availability")
            late.append(event_id)
        if row["supersedes_id"] is not None:
            corrections.append(event_id)
    return {
        "protocol": _PROTOCOL,
        "status": "WITHHELD_LATE_HISTORICAL_POSTINGS" if late else "DECLARED_APPEND_ONLY_CONTINUITY",
        "source": dict(earlier["source"]),
        "earlier_declaration_sha256": _digest({**earlier, "events": sorted(old.values(), key=lambda x: x["event_id"])}),
        "later_declaration_sha256": _digest({**later, "events": sorted(new.values(), key=lambda x: x["event_id"])}),
        "earlier_event_count": len(old),
        "later_event_count": len(new),
        "new_event_count": len(added),
        "new_correction_ids": corrections,
        "late_historical_event_ids": late,
        "earlier_effective_cash_charges": _effective_cash(old, old_superseded),
        "later_effective_cash_charges": _effective_cash(new, new_superseded),
        "settlement_currency": earlier["source"]["settlement_currency"],
        "source_authenticated": False,
        "broker_population_complete_verified": False,
        "independent_checkpoint_verified": False,
        "executable_spreads_or_fills_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "warning": "All event identities, availability times, statement hashes and populations are caller-declared. Late broker postings are normal and require reconciliation; matching local snapshots cannot prove broker completeness, financing, execution quality or profit.",
    }
