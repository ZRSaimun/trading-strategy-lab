"""Offline, point-in-time audit of *declared* CFD financing receipt revisions.

No broker connection, calendar inference, execution, or profitability conclusion.
The caller's schedule, source hashes and publication clocks are unverified.
"""

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation, localcontext

_ID = re.compile(r"[A-Za-z0-9._:-]{1,120}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_AMOUNT = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,2})?\Z")
_SCOPE_KEYS = frozenset((
    "provider", "venue", "instrument", "account_alias", "position_id",
    "settlement_currency", "opened_at", "closed_at", "audit_asof",
    "required_rollovers",
))
_VERSION_KEYS = frozenset((
    "receipt_id", "provider", "venue", "instrument", "account_alias",
    "position_id", "settlement_currency", "rollover_at", "revision",
    "published_at", "ingested_at", "statement_sha256", "amount_currency",
))
_MAX_TIME = 8640000000


def _exact(value, keys, label):
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"Invalid {label} schema")


def _time(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _amount(value):
    if type(value) is not str or _AMOUNT.fullmatch(value) is None or (
        value.startswith("-0") and Decimal(value) == 0
    ):
        raise ValueError("Invalid exact financing amount")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid exact financing amount") from exc
    return number


def _format_money(value):
    with localcontext() as context:
        context.prec = 60
        return format(value.quantize(Decimal("0.01")), ".2f")


def audit_financing_vintages(scope, versions, cutoffs):
    """Select only financing receipts known at each declared as-of cutoff.

    Later revisions never rewrite earlier snapshots. An absent declared receipt
    withholds the *entire* snapshot total; no financing rate is inferred.
    """
    _exact(scope, _SCOPE_KEYS, "financing scope")
    for key in ("provider", "venue", "instrument", "account_alias", "position_id"):
        if not _id(scope[key]):
            raise ValueError("Invalid financing source identity")
    if type(scope["settlement_currency"]) is not str or not _CURRENCY.fullmatch(scope["settlement_currency"]):
        raise ValueError("Invalid settlement currency")
    if not all(_time(scope[k]) for k in ("opened_at", "closed_at", "audit_asof")) or not (
        scope["opened_at"] < scope["closed_at"] <= scope["audit_asof"]
    ):
        raise ValueError("Invalid financing position clock")
    required = scope["required_rollovers"]
    if type(required) is not list or len(required) > 5000:
        raise ValueError("Unbounded declared rollover schedule")
    previous = -1
    for t in required:
        if not _time(t) or not (scope["opened_at"] <= t < scope["closed_at"]) or t <= previous:
            raise ValueError("Unsorted, repeated or out-of-position declared rollover")
        previous = t
    if type(cutoffs) is not list or not 1 <= len(cutoffs) <= 128:
        raise ValueError("Invalid snapshot cutoffs")
    previous = -1
    for t in cutoffs:
        if not _time(t) or not (scope["opened_at"] <= t <= scope["audit_asof"]) or t <= previous:
            raise ValueError("Unsorted, duplicate or future snapshot cutoff")
        previous = t
    if type(versions) is not list or len(versions) > 10000:
        raise ValueError("Unbounded financing revisions")

    grouped = {t: [] for t in required}
    seen_ids = set()
    for row in versions:
        _exact(row, _VERSION_KEYS, "financing revision")
        if not _id(row["receipt_id"]) or row["receipt_id"] in seen_ids:
            raise ValueError("Duplicate or invalid financing receipt ID")
        seen_ids.add(row["receipt_id"])
        for key in ("provider", "venue", "instrument", "account_alias", "position_id", "settlement_currency"):
            if row[key] != scope[key]:
                raise ValueError("Cross-source financing revision")
        if (type(row["rollover_at"]) is not int or row["rollover_at"] not in grouped or
            type(row["revision"]) is not int or row["revision"] < 1 or
            not _time(row["published_at"]) or not _time(row["ingested_at"]) or
            not (row["rollover_at"] <= row["published_at"] <= row["ingested_at"] <= scope["audit_asof"])):
            raise ValueError("Invalid rollover, revision or evidence availability clock")
        if type(row["statement_sha256"]) is not str or not _SHA.fullmatch(row["statement_sha256"]):
            raise ValueError("Invalid financing statement digest")
        amount = _amount(row["amount_currency"])
        grouped[row["rollover_at"]].append((row["revision"], row["published_at"], row["ingested_at"], row["receipt_id"], amount))

    for timestamp, history in grouped.items():
        history.sort(key=lambda r: r[0])
        for index, row in enumerate(history):
            if row[0] != index + 1:
                raise ValueError("Missing or repeated financing revision sequence")
            if index and (row[1] <= history[index-1][1] or row[2] <= history[index-1][2]):
                raise ValueError("Nonmonotonic financing revision availability")

    # A stable diagnostic of the supplied declarations, NOT a trusted timestamp
    # or proof that the input existed before any market outcome was observed.
    canonical = {
        "scope": scope,
        "versions": sorted(versions, key=lambda r: (r["rollover_at"], r["revision"])),
        "cutoffs": cutoffs,
    }
    receipt_sha256 = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    snapshots = []
    for cutoff in cutoffs:
        due = [t for t in required if t <= cutoff]
        missing = []
        selected = []
        with localcontext() as context:
            context.prec = 60
            total = Decimal(0)
            for rollover in due:
                eligible = [r for r in grouped[rollover] if r[1] <= cutoff and r[2] <= cutoff]
                if not eligible:
                    missing.append(rollover)
                    continue
                chosen = eligible[-1]
                selected.append({"rollover_at": rollover, "revision": chosen[0], "receipt_id": chosen[3]})
                total += chosen[4]
            status = "NO_DUE_DECLARED_ROLLOVERS" if not due else (
                "WITHHELD_MISSING_RECEIPTS" if missing else "MATCHED_SELF_DECLARED"
            )
            snapshots.append({
                "cutoff": cutoff,
                "status": status,
                "due_rollovers": len(due),
                "matched_rollovers": len(selected),
                "missing_rollovers": missing,
                "selected_revisions": selected,
                "total_charge_currency": _format_money(total) if status == "MATCHED_SELF_DECLARED" else None,
            })
    return {
        "protocol": "declared-cfd-financing-vintages-v1",
        "declaration_sha256": receipt_sha256,
        "coverage": "SELF_DECLARED_ONLY_NOT_BROKER_AUTHENTICATED",
        "snapshots": snapshots,
        "source_authenticated": False,
        "calendar_complete_verified": False,
        "realized_net_cost_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "warnings": [
            "Rollover schedule, receipt revision order, publication/ingestion clocks and statement hashes are caller declarations.",
            "Earlier snapshots exclude later ingested corrections; missing receipts withhold totals, never imply free financing.",
            "No independent broker authentication, full financing calendar, FX conversion, executable spread or profit verification.",
        ],
    }
