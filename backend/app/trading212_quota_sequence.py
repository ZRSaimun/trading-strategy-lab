"""Disconnected Trading 212 rate-limit receipt sequence audit.

Only caller-supplied adapter observations are read. No network, persistence,
credentials, market-data feed, quota authorization or order execution.
"""
from __future__ import annotations

from datetime import datetime, timezone
import re

_MAX_RECEIPTS = 500
_UTC = re.compile(r"\A\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)\Z")
_ALLOWED_ENDPOINTS = frozenset({"instruments", "exchanges", "account_summary"})
_ALLOWED_STATUSES = frozenset({
    "OBSERVED_UNVERIFIED", "MISSING_REVIEW_REQUIRED", "PARTIAL_REVIEW_REQUIRED",
    "INCONSISTENT_REVIEW_REQUIRED",
})
_FIELDS = ("limit", "period_seconds", "remaining", "reset_unix_seconds", "used")


class QuotaSequenceError(ValueError):
    """Sanitized invalid-input error; never contains supplied receipt values."""


def _utc(value: object) -> datetime:
    if not isinstance(value, str) or not _UTC.fullmatch(value):
        raise QuotaSequenceError("Invalid UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise QuotaSequenceError("Invalid UTC timestamp") from None
    return parsed.astimezone(timezone.utc)


def _quota(observation: object) -> tuple[str, tuple[int, ...] | None]:
    if not isinstance(observation, dict):
        raise QuotaSequenceError("Invalid quota observation")
    status = observation.get("status")
    if not isinstance(status, str) or status not in _ALLOWED_STATUSES:
        raise QuotaSequenceError("Invalid quota observation status")
    if (observation.get("account_quota_verified") is not False or
            observation.get("safe_to_make_another_request") is not False):
        raise QuotaSequenceError("Invalid quota authority flags")
    values = tuple(observation.get(field) for field in _FIELDS)
    if all(value is None for value in values):
        if status != "MISSING_REVIEW_REQUIRED":
            raise QuotaSequenceError("Contradictory quota status")
        return status, None
    if any(value is None for value in values):
        if status != "PARTIAL_REVIEW_REQUIRED":
            raise QuotaSequenceError("Contradictory quota status")
        for value in values:
            if value is not None and (type(value) is not int or value < 0 or value > 10**13):
                raise QuotaSequenceError("Invalid quota counter")
        return status, None
    if any(type(value) is not int or not 0 <= value <= 10**13 for value in values):
        raise QuotaSequenceError("Invalid quota counter")
    limit, period, remaining, reset, used = values
    consistent = (1 <= limit <= 10_000_000 and 1 <= period <= 86_400 and
                  0 <= remaining <= limit and 0 <= used <= limit and
                  1 <= reset <= 253402300799 and used + remaining == limit)
    expected = "OBSERVED_UNVERIFIED" if consistent else "INCONSISTENT_REVIEW_REQUIRED"
    if status != expected:
        raise QuotaSequenceError("Contradictory quota status")
    return status, values if consistent else None


def audit_trading212_quota_sequence(receipts: object, *, as_of_utc: str) -> dict:
    """Audit a chronological list of *untrusted*, caller-supplied GET receipts.

    Same reset timestamp, endpoint and declared account scope are necessary,
    but never sufficient to prove a shared real account or available quota.
    """
    as_of = _utc(as_of_utc)
    if not isinstance(receipts, list) or not 1 <= len(receipts) <= _MAX_RECEIPTS:
        raise QuotaSequenceError("Invalid receipt count")

    issues: dict[str, int] = {}

    def flag(code: str) -> None:
        issues[code] = issues.get(code, 0) + 1

    previous: tuple[datetime, tuple[str, str, str], tuple[int, ...] | None] | None = None
    first_scope: tuple[str, str, str] | None = None
    compared = 0
    transitions = 0
    for item in receipts:
        if not isinstance(item, dict):
            raise QuotaSequenceError("Invalid receipt")
        received = _utc(item.get("received_at_utc"))
        endpoint, environment, account_type = (
            item.get("endpoint"), item.get("environment"), item.get("account_type_declared"))
        if (not isinstance(endpoint, str) or endpoint not in _ALLOWED_ENDPOINTS
                or not isinstance(environment, str) or environment not in ("DEMO", "LIVE")
                or not isinstance(account_type, str) or account_type not in ("INVEST", "STOCKS_ISA")):
            raise QuotaSequenceError("Invalid receipt scope")
        if (item.get("market_data_feed") is not False or
                item.get("may_execute_order") is not False or
                item.get("account_type_verified") is not False):
            raise QuotaSequenceError("Invalid receipt authority flags")
        scope = (endpoint, environment, account_type)
        if first_scope is None:
            first_scope = scope
        elif scope != first_scope:
            flag("SCOPE_CHANGED")
        status, quota = _quota(item.get("rate_limit_observation"))
        if status != "OBSERVED_UNVERIFIED":
            flag("UNVERIFIED_OR_INCOMPLETE_HEADERS")
        if received > as_of:
            flag("RECEIPT_AFTER_AS_OF")
        if quota is not None:
            _, period, _, reset, _ = quota
            reset_time = datetime.fromtimestamp(reset, tz=timezone.utc)
            if reset_time <= received:
                flag("RESET_NOT_AFTER_RECEIPT")
            elif (reset_time - received).total_seconds() > period + 5:
                flag("RESET_BEYOND_DECLARED_PERIOD")
        if previous is not None:
            prev_time, prev_scope, prev_quota = previous
            if received <= prev_time:
                flag("NONINCREASING_RECEIPT_TIME")
            if scope == prev_scope and quota is not None and prev_quota is not None:
                old_limit, old_period, old_remaining, old_reset, old_used = prev_quota
                limit, period, remaining, reset, used = quota
                if reset < old_reset:
                    flag("RESET_MOVED_BACKWARDS")
                if reset == old_reset:
                    if limit != old_limit or period != old_period:
                        flag("WINDOW_POLICY_CHANGED")
                    else:
                        compared += 1
                        if used < old_used or remaining > old_remaining:
                            flag("COUNTERS_REVERSED_WITHIN_WINDOW")
                else:
                    transitions += 1
        previous = (received, scope, quota)

    return {
        "status": "REVIEW_REQUIRED" if issues else "CONSISTENT_UNVERIFIED",
        "receipt_count": len(receipts),
        "same_window_comparison_count": compared,
        "window_transition_count": transitions,
        "issues": dict(sorted(issues.items())),
        "account_identity_verified": False,
        "provider_signature_verified": False,
        "server_clock_attested": False,
        "account_quota_verified": False,
        "safe_to_make_another_request": False,
        "market_data_feed": False,
        "may_execute_order": False,
    }
