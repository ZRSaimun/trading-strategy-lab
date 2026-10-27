"""Read-only reconciliation of *declared* CFD financing events to cash postings.

No broker access, order placement, persistence, inferred charges, or authentication.
One financing event and one cash posting per declared due rollover is an
explicit limited model; split/netted postings require a different adapter.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

_PROTOCOL = "declared-cfd-financing-cash-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MONEY = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,8})?\Z")
_CCY = re.compile(r"[A-Z]{3}\Z")
_SCOPE = {"provider", "venue", "account_alias", "instrument", "position_side",
          "settlement_currency", "position_id", "opened_at_utc", "closed_at_utc",
          "as_of_utc", "calendar_sha256"}
_EVENT = {"event_id", "position_id", "account_alias", "instrument",
          "settlement_currency", "rollover_at_utc", "booked_at_utc",
          "observed_at_utc", "amount", "source_sha256"}
_CASH = {"cash_id", "event_id", "position_id", "account_alias",
         "settlement_currency", "posted_at_utc", "observed_at_utc",
         "amount", "source_sha256"}
_MAX_EVENTS = 3660
_MAX_TIME = 8_640_000_000


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid exact " + label + " schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _epoch(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _amount(value):
    if type(value) is not str or not _MONEY.fullmatch(value):
        raise ValueError("Invalid exact-decimal financing amount")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid exact-decimal financing amount") from exc
    if not number.is_finite() or (number == 0 and value.startswith("-")):
        raise ValueError("Invalid signed financing amount")
    return number


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def audit_declared_financing_cash(scope, due_rollovers, events, cash_postings):
    """Reconcile caller declarations only; never certify authentic broker cash.

    Amounts are signed *cash* deltas: negative debits, positive credits.
    Missing, split, extra, rewritten or cross-source evidence fails closed.
    """
    _exact(scope, _SCOPE, "financing scope")
    if not all(_id(scope[k]) for k in ("provider", "venue", "account_alias",
                                        "instrument", "position_id")):
        raise ValueError("Invalid financing source or position identity")
    if (scope["position_side"] not in ("LONG", "SHORT") or
            type(scope["settlement_currency"]) is not str or
            not _CCY.fullmatch(scope["settlement_currency"]) or
            not _sha(scope["calendar_sha256"])):
        raise ValueError("Invalid financing side, currency or calendar fingerprint")
    if (not all(_epoch(scope[k]) for k in ("opened_at_utc", "closed_at_utc", "as_of_utc"))
            or not scope["opened_at_utc"] < scope["closed_at_utc"] <= scope["as_of_utc"]):
        raise ValueError("Invalid position and observation chronology")
    if (type(due_rollovers) is not list or len(due_rollovers) > _MAX_EVENTS or
            any(not _epoch(t) for t in due_rollovers) or
            any(not scope["opened_at_utc"] <= t < scope["closed_at_utc"] for t in due_rollovers) or
            any(b <= a for a, b in zip(due_rollovers, due_rollovers[1:]))):
        raise ValueError("Invalid, duplicated or out-of-position due rollover census")
    if (type(events) is not list or type(cash_postings) is not list or
            len(events) != len(due_rollovers) or len(cash_postings) != len(due_rollovers)):
        raise ValueError("Missing, extra or unsupported split financing/cash population")

    by_id = {}
    seen_rollovers = []
    total = Decimal("0")
    late_bookings = 0
    for event in events:
        _exact(event, _EVENT, "financing event")
        if (not _id(event["event_id"]) or event["event_id"] in by_id or
                event["position_id"] != scope["position_id"] or
                event["account_alias"] != scope["account_alias"] or
                event["instrument"] != scope["instrument"] or
                event["settlement_currency"] != scope["settlement_currency"] or
                not _sha(event["source_sha256"])):
            raise ValueError("Duplicate or cross-source financing event")
        if (not all(_epoch(event[k]) for k in ("rollover_at_utc", "booked_at_utc", "observed_at_utc"))
                or not event["rollover_at_utc"] <= event["booked_at_utc"] <=
                event["observed_at_utc"] <= scope["as_of_utc"]):
            raise ValueError("Invalid financing event chronology")
        amount = _amount(event["amount"])
        if amount == 0:
            raise ValueError("Zero financing requires separately verified waiver evidence")
        seen_rollovers.append(event["rollover_at_utc"])
        by_id[event["event_id"]] = (event, amount)
        total += amount
        late_bookings += int(event["booked_at_utc"] >= scope["closed_at_utc"])
    if seen_rollovers != due_rollovers:
        raise ValueError("Financing event and due rollover census mismatch")

    seen_cash = set()
    seen_event_ids = set()
    delayed_cash = 0
    for cash in cash_postings:
        _exact(cash, _CASH, "cash posting")
        if (not _id(cash["cash_id"]) or cash["cash_id"] in seen_cash or
                cash["event_id"] not in by_id or cash["event_id"] in seen_event_ids or
                cash["position_id"] != scope["position_id"] or
                cash["account_alias"] != scope["account_alias"] or
                cash["settlement_currency"] != scope["settlement_currency"] or
                not _sha(cash["source_sha256"])):
            raise ValueError("Duplicate, missing or cross-source cash posting")
        event, amount = by_id[cash["event_id"]]
        if (not all(_epoch(cash[k]) for k in ("posted_at_utc", "observed_at_utc")) or
                not event["booked_at_utc"] <= cash["posted_at_utc"] <=
                cash["observed_at_utc"] <= scope["as_of_utc"]):
            raise ValueError("Invalid cash settlement chronology")
        if _amount(cash["amount"]) != amount:
            raise ValueError("Cash amount disagrees with financing event")
        seen_cash.add(cash["cash_id"])
        seen_event_ids.add(cash["event_id"])
        delayed_cash += int(cash["posted_at_utc"] >= scope["closed_at_utc"])
    if seen_event_ids != set(by_id):
        raise ValueError("Unreconciled financing event population")

    return {
        "protocol": _PROTOCOL,
        "status": "NO_DUE_ROLLOVERS_UNVERIFIED" if not due_rollovers else "DECLARED_ONE_TO_ONE_MATCH_ONLY",
        "declared_evidence_sha256": _digest({"protocol": _PROTOCOL, "scope": scope,
                                             "due_rollovers": due_rollovers,
                                             "events": events, "cash_postings": cash_postings}),
        "calendar_sha256": scope["calendar_sha256"],
        "declared_rollover_count": len(due_rollovers),
        "declared_event_count": len(events),
        "declared_cash_posting_count": len(cash_postings),
        "declared_net_cash_delta": format(total, "f"),
        "declared_net_financing_cost": format(-total, "f"),
        "settlement_currency": scope["settlement_currency"],
        "events_booked_after_close": late_bookings,
        "cash_postings_after_close": delayed_cash,
        "broker_source_authenticated": False,
        "cash_ledger_independently_verified": False,
        "rates_at_decision_time_verified": False,
        "fx_conversion_verified": False,
        "untouched_holdout_or_profit_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "All identifiers, digests, clocks, amounts and populations are caller-declared. "
                   "One event/one posting per due rollover is a limited retrospective model, "
                   "not a broker statement, rate vintage, FX conversion, or trading edge.",
    }
