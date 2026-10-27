"""Offline, source-bound CFD rollover calendar coverage and DST audit.

This validates *declared* daily broker schedule evidence, not the broker's
actual calendar, cash debits, historic rate availability, or trading returns.
No network, orders, archive reads, persistence, or inferred weekend charges.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
import hashlib
import json
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_PROTOCOL = "declared-cfd-rollover-calendar-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CCY = re.compile(r"[A-Z]{3}\Z")
_ZONE = re.compile(r"[A-Za-z0-9_+-]+(?:/[A-Za-z0-9_+-]+){0,2}\Z")
_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_CLOCK = re.compile(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]\Z")
_SCOPE = {"provider", "venue", "account_alias", "instrument", "position_side",
          "settlement_currency", "timezone", "local_cutoff", "opened_at_utc",
          "closed_at_utc", "as_of_utc", "registered_at_utc", "calendar_source_sha256"}
_ENTRY = {"local_date", "cutoff_at_utc", "fold", "offset_minutes", "kind",
          "multiplier", "reason", "evidence_sha256", "published_at_utc", "ingested_at_utc"}
_REASONS = {"MARKET_CLOSED", "HOLIDAY", "BROKER_WAIVER", "BROKER_NO_EVENT"}
_MAX_TIME = 8_640_000_000
_MAX_DAYS = 3660


def _exact(value, fields, label):
    if type(value) is not dict or set(value) != fields:
        raise ValueError("Invalid exact " + label + " schema")


def _epoch(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _parse_day(value):
    if type(value) is not str or not _DAY.fullmatch(value):
        raise ValueError("Invalid local calendar date")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("Invalid local calendar date") from exc
    if not 2000 <= parsed.year <= 2100:
        raise ValueError("Local date outside bounded research years")
    return parsed


def _scope(scope):
    _exact(scope, _SCOPE, "rollover scope")
    if not all(type(scope[k]) is str and _ID.fullmatch(scope[k]) for k in
               ("provider", "venue", "account_alias", "instrument")):
        raise ValueError("Invalid rollover source identity")
    if (scope["position_side"] not in ("LONG", "SHORT") or
        type(scope["settlement_currency"]) is not str or
        not _CCY.fullmatch(scope["settlement_currency"])):
        raise ValueError("Invalid side or settlement currency")
    zone_name = scope["timezone"]
    if type(zone_name) is not str or len(zone_name) > 64 or not _ZONE.fullmatch(zone_name):
        raise ValueError("Invalid IANA timezone")
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("Unknown IANA timezone") from exc
    if type(scope["local_cutoff"]) is not str or not _CLOCK.fullmatch(scope["local_cutoff"]):
        raise ValueError("Invalid local cutoff clock")
    if not all(_epoch(scope[k]) for k in
               ("opened_at_utc", "closed_at_utc", "as_of_utc", "registered_at_utc")):
        raise ValueError("Invalid rollover scope epoch")
    if not (scope["opened_at_utc"] < scope["closed_at_utc"] <=
            scope["registered_at_utc"] <= scope["as_of_utc"]):
        raise ValueError("Invalid position, registration or audit chronology")
    if type(scope["calendar_source_sha256"]) is not str or not _SHA.fullmatch(scope["calendar_source_sha256"]):
        raise ValueError("Invalid declared calendar source digest")
    first = datetime.fromtimestamp(scope["opened_at_utc"], timezone.utc).astimezone(zone).date()
    last = datetime.fromtimestamp(scope["closed_at_utc"], timezone.utc).astimezone(zone).date()
    count = (last - first).days + 1
    if not 1 <= count <= _MAX_DAYS:
        raise ValueError("Unbounded position calendar coverage")
    return zone, first, last, count


def _validate(scope, days):
    zone, first, last, count = _scope(scope)
    if type(days) is not list or len(days) != count:
        raise ValueError("Missing, extra or unbounded daily calendar census")
    hour, minute = map(int, scope["local_cutoff"].split(":"))
    charge_due = []
    late_evidence = []
    charged_multiplier = 0
    for i, row in enumerate(days):
        _exact(row, _ENTRY, "rollover day")
        day = _parse_day(row["local_date"])
        if day != first + timedelta(days=i):
            raise ValueError("Missing, duplicated or reordered local calendar day")
        if (not _epoch(row["cutoff_at_utc"]) or row["cutoff_at_utc"] > scope["as_of_utc"] or
            type(row["fold"]) is not int or
            row["fold"] not in (0, 1) or type(row["offset_minutes"]) is not int or
            not -840 <= row["offset_minutes"] <= 840):
            raise ValueError("Invalid rollover cutoff, offset or DST fold")
        local = datetime(day.year, day.month, day.day, hour, minute,
                         tzinfo=zone, fold=row["fold"])
        utc = local.astimezone(timezone.utc)
        restored = utc.astimezone(zone)
        if (restored.replace(tzinfo=None) != local.replace(tzinfo=None) or
            restored.fold != row["fold"] or
            int(utc.timestamp()) != row["cutoff_at_utc"] or
            int(local.utcoffset().total_seconds()) != row["offset_minutes"] * 60):
            raise ValueError("Nonexistent, ambiguous or mismatched local rollover cutoff")
        if (not _epoch(row["published_at_utc"]) or not _epoch(row["ingested_at_utc"]) or
            not row["published_at_utc"] <= row["ingested_at_utc"] <= scope["registered_at_utc"] or
            type(row["evidence_sha256"]) is not str or not _SHA.fullmatch(row["evidence_sha256"])):
            raise ValueError("Invalid calendar evidence identity or availability")
        if row["kind"] == "CHARGE":
            if (type(row["multiplier"]) is not int or not 1 <= row["multiplier"] <= 7 or
                row["reason"] != "BROKER_ROLLOVER"):
                raise ValueError("Invalid explicit broker rollover multiplier")
        elif row["kind"] == "NO_CHARGE":
            if (type(row["multiplier"]) is not int or row["multiplier"] != 0 or
                type(row["reason"]) is not str or row["reason"] not in _REASONS):
                raise ValueError("Unverified no-charge calendar declaration")
        else:
            raise ValueError("Unknown rollover calendar status")
        if scope["opened_at_utc"] <= row["cutoff_at_utc"] < scope["closed_at_utc"]:
            if row["kind"] == "CHARGE":
                charge_due.append(row["cutoff_at_utc"])
                charged_multiplier += row["multiplier"]
            if row["ingested_at_utc"] > row["cutoff_at_utc"]:
                late_evidence.append(row["local_date"])
    return charge_due, charged_multiplier, late_evidence, first, last


def fingerprint_declared_rollover_calendar(scope, days):
    """Unsigned fingerprint of caller declarations, never a broker signature."""
    _validate(scope, days)
    return _digest({"protocol": _PROTOCOL, "scope": scope, "days": days})


def audit_declared_rollover_calendar(scope, days, expected_calendar_sha256,
                                     expected_charge_timestamps):
    """Reconcile full daily coverage to separately declared due rollover clocks.

    A matching hash and census do not independently authenticate a calendar.
    The output cannot authorize any live/demo order or certify financing costs.
    """
    charge_due, multiplier, late, first, last = _validate(scope, days)
    digest = _digest({"protocol": _PROTOCOL, "scope": scope, "days": days})
    if (type(expected_calendar_sha256) is not str or not _SHA.fullmatch(expected_calendar_sha256)
            or digest != expected_calendar_sha256):
        raise ValueError("Declared rollover calendar fingerprint mismatch")
    if (type(expected_charge_timestamps) is not list or
            len(expected_charge_timestamps) > _MAX_DAYS or
            any(not _epoch(t) for t in expected_charge_timestamps) or
            expected_charge_timestamps != charge_due):
        raise ValueError("Due rollover population mismatch; financing must be withheld")
    return {
        "protocol": _PROTOCOL,
        "status": ("NO_DECLARED_DUE_ROLLOVERS_UNVERIFIED" if not charge_due else
                   "RETROSPECTIVE_DECLARATIONS_ONLY" if late else "PRE_CUTOFF_DECLARATIONS_ONLY"),
        "calendar_sha256": digest,
        "coverage_first_date": first.isoformat(),
        "coverage_last_date": last.isoformat(),
        "calendar_days": len(days),
        "distinct_calendar_years": last.year - first.year + 1,
        "at_least_three_calendar_years": last.year - first.year + 1 >= 3,
        "declared_due_rollovers": charge_due,
        "declared_total_multiplier": multiplier,
        "late_evidence_dates": late[:25],
        "late_evidence_count": len(late),
        "source_authenticated": False,
        "calendar_completeness_independently_verified": False,
        "rates_or_cash_charges_verified": False,
        "decision_time_registration_verified": False,
        "verified_profitability": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": ("Daily statuses, multipliers, source digests and timestamps are caller-declared; "
                    "matching declarations cannot prove broker calendar completeness or financing. "
                    "Late evidence is not decision-time evidence. No rate, cash ledger, FX, "
                    "broker fills, untouched holdout or trading edge is verified."),
    }
