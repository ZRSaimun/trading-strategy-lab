"""Fail-closed, offline point-in-time CFD overnight-rate assumption review.

Rates, rollover calendars, notionals, source IDs and publication clocks are
caller-declared, NOT authenticated broker evidence. No execution or P&L claims.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

_PROTOCOL = "declared-cfd-rate-decision-audit-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_POSITIVE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_SIGNED_RATE = re.compile(r"-?(?:0|[1-9][0-9]{0,4})(?:\.[0-9]{1,6})?\Z")
_SOURCE = frozenset({"provider", "venue", "account_alias", "instrument", "settlement_currency"})
_SCOPE = frozenset({"protocol", "source", "opened_at", "closed_at", "audit_asof", "rollovers"})
_ROLLOVER = frozenset({"rollover_id", "rollover_at", "decision_at", "side", "notional_cash", "day_multiplier"})
_RATE = frozenset({"rate_id", "rollover_id", "revision", "published_at", "ingested_at",
                   "long_bps_per_day", "short_bps_per_day", "statement_sha256"}) | _SOURCE
_MAX_TIME = 8640000000


def _exact(obj, keys, label):
    if type(obj) is not dict or set(obj) != keys:
        raise ValueError("Invalid " + label + " schema")


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _decimal(value, pattern, label):
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise ValueError("Invalid exact " + label)
    result = Decimal(value)
    if result == 0 and value.startswith("-"):
        raise ValueError("Negative zero " + label)
    return result


def _sha(obj):
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _validate_scope(scope):
    _exact(scope, _SCOPE, "rate decision scope")
    if scope["protocol"] != _PROTOCOL:
        raise ValueError("Unknown rate decision protocol")
    source = scope["source"]
    _exact(source, _SOURCE, "source identity")
    if not all(_id(source[k]) for k in _SOURCE - {"settlement_currency"}):
        raise ValueError("Invalid rate source identity")
    if type(source["settlement_currency"]) is not str or not _CURRENCY.fullmatch(source["settlement_currency"]):
        raise ValueError("Invalid settlement currency")
    if not all(_clock(scope[k]) for k in ("opened_at", "closed_at", "audit_asof")) or not (
        scope["opened_at"] < scope["closed_at"] <= scope["audit_asof"]
    ):
        raise ValueError("Invalid position clocks")
    rollovers = scope["rollovers"]
    if type(rollovers) is not list or not 1 <= len(rollovers) <= 5000:
        raise ValueError("Invalid bounded required rollover population")
    ids = set()
    previous = -1
    for row in rollovers:
        _exact(row, _ROLLOVER, "rollover decision")
        if not _id(row["rollover_id"]) or row["rollover_id"] in ids:
            raise ValueError("Duplicate or invalid rollover identity")
        ids.add(row["rollover_id"])
        if not _clock(row["rollover_at"]) or not _clock(row["decision_at"]) or not (
            scope["opened_at"] <= row["decision_at"] <= row["rollover_at"] < scope["closed_at"]
        ) or row["rollover_at"] <= previous:
            raise ValueError("Invalid causal rollover decision clock or ordering")
        previous = row["rollover_at"]
        if row["side"] not in ("LONG", "SHORT") or type(row["side"]) is not str:
            raise ValueError("Invalid rollover direction")
        if _decimal(row["notional_cash"], _POSITIVE, "notional") <= 0:
            raise ValueError("Nonpositive rollover notional")
        if type(row["day_multiplier"]) is not int or not 1 <= row["day_multiplier"] <= 7:
            raise ValueError("Invalid explicit day multiplier")
    return {r["rollover_id"]: r for r in rollovers}


def fingerprint_cfd_rate_decisions(scope):
    """Stable declaration digest; NOT a trusted or pre-outcome registration."""
    _validate_scope(scope)
    return _sha(scope)


def audit_declared_cfd_rate_decisions(scope, rates, expected_scope_sha256):
    """Estimate *declared-only* signed financing using rates known at each decision.

    Missing as-of rates withhold the entire estimate; later corrections never
    rewrite earlier decisions. Does not model broker-specific rounding, actual
    debits, position valuation, or prove that the supplied schedule is complete.
    """
    expected = _validate_scope(scope)
    if type(expected_scope_sha256) is not str or not _SHA.fullmatch(expected_scope_sha256):
        raise ValueError("Expected scope digest required")
    digest = fingerprint_cfd_rate_decisions(scope)
    if digest != expected_scope_sha256:
        raise ValueError("Rate decision scope digest mismatch")
    if type(rates) is not list or len(rates) > 10000:
        raise ValueError("Invalid bounded rate version population")
    grouped = {rid: [] for rid in expected}
    ids = set()
    for row in rates:
        _exact(row, _RATE, "rate version")
        if not _id(row["rate_id"]) or row["rate_id"] in ids:
            raise ValueError("Duplicate or invalid rate ID")
        ids.add(row["rate_id"])
        if any(row[k] != scope["source"][k] for k in _SOURCE):
            raise ValueError("Cross-source rate version")
        if type(row["rollover_id"]) is not str or row["rollover_id"] not in grouped:
            raise ValueError("Unregistered rollover rate")
        if type(row["revision"]) is not int or not 1 <= row["revision"] <= 10000:
            raise ValueError("Invalid rate revision")
        if not _clock(row["published_at"]) or not _clock(row["ingested_at"]) or not (
            row["published_at"] <= row["ingested_at"] <= scope["audit_asof"]
        ):
            raise ValueError("Invalid rate availability clock")
        for field in ("long_bps_per_day", "short_bps_per_day"):
            _decimal(row[field], _SIGNED_RATE, field)
        if type(row["statement_sha256"]) is not str or not _SHA.fullmatch(row["statement_sha256"]):
            raise ValueError("Invalid statement checksum")
        grouped[row["rollover_id"]].append(row)
    for history in grouped.values():
        history.sort(key=lambda r: r["revision"])
        for index, row in enumerate(history):
            if row["revision"] != index + 1:
                raise ValueError("Missing or repeated rate revision")
            if index and not (
                history[index - 1]["published_at"] < row["published_at"]
                and history[index - 1]["ingested_at"] < row["ingested_at"]
            ):
                raise ValueError("Nonmonotonic rate revision availability")
    details = []
    missing = []
    with localcontext() as context:
        context.prec = 80
        total = Decimal(0)
        for rollover in scope["rollovers"]:
            rid = rollover["rollover_id"]
            known = [r for r in grouped[rid] if r["published_at"] <= rollover["decision_at"]
                     and r["ingested_at"] <= rollover["decision_at"]]
            if not known:
                missing.append(rid)
                details.append({"rollover_id": rid, "status": "WITHHELD_RATE_NOT_KNOWN_AT_DECISION",
                                "selected_rate_id": None, "revision": None, "estimated_cash_unrounded": None})
                continue
            selected = known[-1]
            field = "long_bps_per_day" if rollover["side"] == "LONG" else "short_bps_per_day"
            charge = (_decimal(rollover["notional_cash"], _POSITIVE, "notional")
                      * _decimal(selected[field], _SIGNED_RATE, "rate")
                      * rollover["day_multiplier"] / Decimal(10000))
            total += charge
            details.append({"rollover_id": rid, "status": "SELF_DECLARED_RATE_AT_DECISION",
                            "selected_rate_id": selected["rate_id"], "revision": selected["revision"],
                            "estimated_cash_unrounded": format(charge, "f")})
    return {
        "protocol": _PROTOCOL,
        "source_identity": dict(scope["source"]),
        "scope_sha256": digest,
        "rate_declarations_sha256": _sha({"scope_sha256": digest, "rates": sorted(rates, key=lambda r: (r["rollover_id"], r["revision"]))}),
        "status": "WITHHELD_MISSING_ASOF_RATE" if missing else "COMPLETE_SELF_DECLARED_ONLY",
        "required_rollovers": len(expected),
        "matched_rollovers": len(expected) - len(missing),
        "missing_rollover_ids": missing,
        "estimated_financing_cash_unrounded": None if missing else format(total, "f"),
        "rollovers": details,
        "source_authenticated": False,
        "complete_broker_calendar_verified": False,
        "broker_rounding_verified": False,
        "realized_financing_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "warning": ("Caller-declared rates, notional, timestamps, explicit day multipliers and statement hashes "
                    "are unauthenticated. No broker calendar, triple rollover, holiday, cash rounding, "
                    "position valuation, realized cost or trading edge is proven."),
    }
