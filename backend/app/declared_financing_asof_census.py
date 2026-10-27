"""Offline, declared-only point-in-time CFD financing receipt availability audit.

No network, broker access, orders, persistence, archive ingestion or P&L.
Historical receipt availability is self-declared and cannot prove broker provenance.
"""
from __future__ import annotations

from decimal import Decimal
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CCY = re.compile(r"[A-Z]{3}\Z")
_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,8})?\Z")
_SCOPE = {"provider", "venue", "account_alias", "instrument", "position_id",
          "settlement_currency", "opened_at_utc", "closed_at_utc", "as_of_utc",
          "calendar_sha256"}
_EVENT = {"event_id", "rollover_at_utc", "booked_at_utc", "observed_at_utc",
          "amount", "source_sha256", "provider", "venue", "account_alias",
          "instrument", "position_id", "settlement_currency"}
_CASH = {"cash_id", "event_id", "posted_at_utc", "observed_at_utc", "amount",
         "source_sha256", "provider", "venue", "account_alias", "instrument",
         "position_id", "settlement_currency"}
_MAX_EVENTS = 3660
_MAX_CUTOFFS = 1000
_MAX_EPOCH = 8_640_000_000


def _exact(value, fields):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid exact declaration schema")


def _epoch(value):
    return type(value) is int and 0 <= value <= _MAX_EPOCH


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _amount(value):
    if type(value) is not str or not _AMOUNT.fullmatch(value):
        raise ValueError("Invalid exact decimal amount")
    amount = Decimal(value)
    if amount == 0 and value.startswith("-"):
        raise ValueError("Negative zero is not a valid cash amount")
    if amount == 0:
        raise ValueError("Zero financing needs independently verified waiver evidence")
    return amount


def audit_declared_financing_asof(scope, due_rollovers, events, cash_postings, cutoffs):
    """Return no cash total until *all* declared due receipts were observable.

    Future receipts are validated for integrity but excluded from earlier snapshots.
    An incomplete snapshot has a null cash delta, never a partial/zero estimate.
    """
    _exact(scope, _SCOPE)
    if (not all(_id(scope[k]) for k in ("provider", "venue", "account_alias",
                                         "instrument", "position_id")) or
            type(scope["settlement_currency"]) is not str or
            not _CCY.fullmatch(scope["settlement_currency"]) or
            not _sha(scope["calendar_sha256"])):
        raise ValueError("Invalid source identity")
    if (not all(_epoch(scope[k]) for k in
                ("opened_at_utc", "closed_at_utc", "as_of_utc")) or
            not scope["opened_at_utc"] < scope["closed_at_utc"] <= scope["as_of_utc"]):
        raise ValueError("Invalid scope chronology")
    if (type(due_rollovers) is not list or len(due_rollovers) > _MAX_EVENTS or
            any(not _epoch(t) or not scope["opened_at_utc"] <= t < scope["closed_at_utc"]
                for t in due_rollovers) or
            any(b <= a for a, b in zip(due_rollovers, due_rollovers[1:]))):
        raise ValueError("Invalid declared rollover population")
    if (type(cutoffs) is not list or not 1 <= len(cutoffs) <= _MAX_CUTOFFS or
            any(not _epoch(t) or not scope["opened_at_utc"] <= t <= scope["as_of_utc"]
                for t in cutoffs) or
            any(b <= a for a, b in zip(cutoffs, cutoffs[1:]))):
        raise ValueError("Invalid chronological as-of cutoffs")
    if (type(events) is not list or type(cash_postings) is not list or
            len(events) > len(due_rollovers) or len(cash_postings) > len(events)):
        raise ValueError("Invalid receipt population")

    due_set = set(due_rollovers)
    by_event = {}
    by_rollover = {}
    for event in events:
        _exact(event, _EVENT)
        if (any(event[k] != scope[k] for k in ("provider", "venue", "account_alias",
                                             "instrument", "position_id",
                                             "settlement_currency")) or
                not _id(event["event_id"]) or event["event_id"] in by_event or
                not _sha(event["source_sha256"]) or
                not all(_epoch(event[k]) for k in
                        ("rollover_at_utc", "booked_at_utc", "observed_at_utc")) or
                event["rollover_at_utc"] not in due_set or
                event["rollover_at_utc"] in by_rollover or
                not event["rollover_at_utc"] <= event["booked_at_utc"] <=
                    event["observed_at_utc"] <= scope["as_of_utc"]):
            raise ValueError("Invalid, duplicate or future financing event")
        amount = _amount(event["amount"])
        by_event[event["event_id"]] = (event, amount)
        by_rollover[event["rollover_at_utc"]] = event["event_id"]

    by_cash_event = {}
    cash_ids = set()
    for cash in cash_postings:
        _exact(cash, _CASH)
        if (any(cash[k] != scope[k] for k in ("provider", "venue", "account_alias",
                                            "instrument", "position_id",
                                            "settlement_currency")) or
                not _id(cash["cash_id"]) or cash["cash_id"] in cash_ids or
                not _id(cash["event_id"]) or cash["event_id"] not in by_event or
                cash["event_id"] in by_cash_event or
                not _sha(cash["source_sha256"]) or
                not all(_epoch(cash[k]) for k in
                        ("posted_at_utc", "observed_at_utc"))):
            raise ValueError("Invalid, duplicate or cross-event cash receipt")
        event, amount = by_event[cash["event_id"]]
        if (not event["booked_at_utc"] <= cash["posted_at_utc"] <=
                cash["observed_at_utc"] <= scope["as_of_utc"] or
                _amount(cash["amount"]) != amount):
            raise ValueError("Invalid cash chronology or mismatched amount")
        cash_ids.add(cash["cash_id"])
        by_cash_event[cash["event_id"]] = cash

    snapshots = []
    for cutoff in cutoffs:
        due = [t for t in due_rollovers if t <= cutoff]
        if not due:
            snapshots.append({"cutoff_at_utc": cutoff, "status": "NO_DUE_YET_UNVERIFIED",
                              "due_count": 0, "complete_count": 0,
                              "unknown_count": 0, "net_cash_delta": None})
            continue
        total = Decimal("0")
        complete = 0
        for t in due:
            event_id = by_rollover.get(t)
            if event_id is None:
                continue
            event, amount = by_event[event_id]
            cash = by_cash_event.get(event_id)
            if (cash is None or event["observed_at_utc"] > cutoff or
                    cash["observed_at_utc"] > cutoff):
                continue
            complete += 1
            total += amount
        unknown = len(due) - complete
        snapshots.append({"cutoff_at_utc": cutoff,
                          "status": "DECLARED_COMPLETE_ONLY" if unknown == 0
                                    else "INCOMPLETE_AS_OF",
                          "due_count": len(due), "complete_count": complete,
                          "unknown_count": unknown,
                          "net_cash_delta": format(total, "f") if unknown == 0 else None})
    return {"protocol": "declared-financing-asof-census-v1",
            "source_identity": {k: scope[k] for k in
                                ("provider", "venue", "account_alias", "instrument",
                                 "position_id", "settlement_currency", "calendar_sha256")},
            "snapshots": snapshots, "broker_source_authenticated": False,
            "historical_receipt_clocks_independently_verified": False,
            "profitability_verified": False, "may_execute_demo_order": False,
            "may_execute_real_order": False,
            "warning": "All source identities, due rollovers, receipt amounts and availability "
                       "clocks are caller-declared. No real broker evidence is authenticated."}
