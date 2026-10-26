"""Fail-closed, bounded census of already-validated OANDA practice ID ranges.

No order API, credentials, persistence, or network in the audit path. Optional
read wrapper uses only the companion GET-only practice idrange adapter.
Caller-supplied reports and their hashes are not independently authenticated.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
import hashlib
import json
import re

_ACCOUNT = re.compile(r"[0-9]{3}-[0-9]{3}-[0-9]{4,12}-[0-9]{3}\Z")
_ID = re.compile(r"[1-9][0-9]{0,19}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_TYPE = re.compile(r"[A-Z][A-Z0-9_]{1,63}\Z")
_PER_WINDOW = 100
_MAX_WINDOWS = 20
_MAX_IDS = _PER_WINDOW * _MAX_WINDOWS
_REPORT_KEYS = frozenset({
    "provider", "account_id", "requested_first_id", "requested_last_id",
    "broker_reported_latest_id", "observed_ids", "observed_count",
    "missing_id_count", "observed_contiguous_id_range", "observed_type_counts",
    "canonical_response_sha256", "original_response_bytes_authenticated",
    "complete_broker_history_authenticated", "cash_ledger_reconciled",
    "may_execute_demo_order", "may_execute_real_order",
})


def _id(value, label):
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ValueError("Invalid " + label)
    return int(value)


def _windows(first_id, last_id):
    first, last = _id(first_id, "first transaction ID"), _id(last_id, "last transaction ID")
    if last < first or last - first + 1 > _MAX_IDS:
        raise ValueError("Unbounded or reversed transaction census")
    return [(str(start), str(min(start + _PER_WINDOW - 1, last)))
            for start in range(first, last + 1, _PER_WINDOW)]


def plan_practice_transaction_windows(first_id, last_id):
    """Return adjacent, non-overlapping ID ranges; at most 20 GET-sized windows."""
    return _windows(first_id, last_id)


def _validate_report(report, first, last, account, pinned):
    if type(report) is not dict or set(report) != _REPORT_KEYS:
        raise ValueError("Invalid exact practice window report schema")
    if (report["provider"] != "OANDA_V20_PRACTICE"
            or report["account_id"] != account
            or report["requested_first_id"] != first
            or report["requested_last_id"] != last):
        raise ValueError("Practice window source or range mismatch")
    if (_id(report["broker_reported_latest_id"], "reported cursor") != pinned
            or report["broker_reported_latest_id"] != str(pinned)):
        raise ValueError("Practice snapshot cursor drift")
    for field in ("original_response_bytes_authenticated",
                  "complete_broker_history_authenticated", "cash_ledger_reconciled",
                  "may_execute_demo_order", "may_execute_real_order"):
        if report[field] is not False:
            raise ValueError("Unsubstantiated practice trust or execution claim")
    digest = report["canonical_response_sha256"]
    if type(digest) is not str or _SHA.fullmatch(digest) is None:
        raise ValueError("Invalid practice response digest")
    ids = report["observed_ids"]
    start, end = int(first), int(last)
    if type(ids) is not list or len(ids) > end - start + 1:
        raise ValueError("Invalid observed ID population")
    previous = start - 1
    for value in ids:
        number = _id(value, "observed transaction ID")
        if not previous < number <= end:
            raise ValueError("Unsorted, duplicate or out-of-range transaction")
        previous = number
    missing = end - start + 1 - len(ids)
    if (type(report["observed_count"]) is not int
            or report["observed_count"] != len(ids)
            or type(report["missing_id_count"]) is not int
            or report["missing_id_count"] != missing
            or type(report["observed_contiguous_id_range"]) is not bool
            or report["observed_contiguous_id_range"] != (missing == 0)):
        raise ValueError("Inconsistent practice window coverage counters")
    counts = report["observed_type_counts"]
    if type(counts) is not dict or len(counts) > 100:
        raise ValueError("Invalid practice event-type population")
    for kind, count in counts.items():
        if (type(kind) is not str or _TYPE.fullmatch(kind) is None
                or type(count) is not int or count < 1 or count > len(ids)):
            raise ValueError("Invalid practice event-type count")
    if sum(counts.values()) != len(ids):
        raise ValueError("Practice event types do not reconcile")
    return ids, counts


def audit_practice_transaction_windows(
    reports, *, account_id, first_id, last_id, snapshot_last_id,
    expected_census_sha256=None,
):
    """Audit a pinned, exact partition of caller-declared validated reports.

    A zero-gap declared census is not authenticated brokerage history. An
    optional externally preserved hash detects change only if its custody is
    independent of the reports; the hash alone cannot authenticate a broker.
    """
    if type(account_id) is not str or _ACCOUNT.fullmatch(account_id) is None:
        raise ValueError("Invalid practice account identity")
    windows = _windows(first_id, last_id)
    pinned = _id(snapshot_last_id, "pinned snapshot cursor")
    if pinned < int(last_id):
        raise ValueError("Snapshot cursor precedes requested history")
    if type(reports) is not list or len(reports) != len(windows):
        raise ValueError("Incomplete or duplicated practice window partition")
    if (expected_census_sha256 is not None and
            (type(expected_census_sha256) is not str or
             _SHA.fullmatch(expected_census_sha256) is None)):
        raise ValueError("Invalid expected census fingerprint")
    seen = 0
    missing_count = 0
    missing_sample = []
    type_counts = Counter()
    for report, (start, end) in zip(reports, windows):
        ids, counts = _validate_report(report, start, end, account_id, pinned)
        seen += len(ids)
        type_counts.update(counts)
        # Bounded evidence sample; never construct a potentially huge gap list.
        previous = int(start) - 1
        for value in ids + [str(int(end) + 1)]:
            current = int(value)
            gap = current - previous - 1
            missing_count += gap
            if len(missing_sample) < 20 and gap:
                take = min(gap, 20 - len(missing_sample))
                missing_sample.extend(str(n) for n in range(previous + 1, previous + 1 + take))
            previous = current
    if seen + missing_count != int(last_id) - int(first_id) + 1:
        raise ValueError("Unreconciled practice transaction population")
    canonical = json.dumps({
        "provider": "OANDA_V20_PRACTICE", "account_id": account_id,
        "first_id": first_id, "last_id": last_id,
        "snapshot_last_id": snapshot_last_id, "windows": reports,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False).encode("utf-8")
    digest = hashlib.sha256(canonical).hexdigest()
    if expected_census_sha256 is not None and digest != expected_census_sha256:
        raise ValueError("Practice census differs from externally frozen fingerprint")
    return {
        "provider": "OANDA_V20_PRACTICE", "account_id": account_id,
        "requested_first_id": first_id, "requested_last_id": last_id,
        "pinned_snapshot_last_id": snapshot_last_id,
        "window_count": len(windows), "observed_count": seen,
        "missing_declared_id_count": missing_count,
        "missing_declared_id_sample": missing_sample,
        "observed_type_counts": dict(sorted(type_counts.items())),
        "declared_window_status": ("NO_GAPS_IN_DECLARED_RANGES" if missing_count == 0
                                   else "MISSING_IDS_IN_DECLARED_RANGES"),
        "census_sha256": digest,
        "original_response_bytes_authenticated": False,
        "complete_broker_history_authenticated": False,
        "cash_ledger_reconciled": False,
        "may_execute_demo_order": False, "may_execute_real_order": False,
    }


def inspect_practice_transaction_windows(
    adapter, first_id, last_id, *, as_of, snapshot_last_id,
    max_requests=10, expected_census_sha256=None,
):
    """Optional bounded GET-only inspection via the existing practice adapter.

    The adapter itself is network-disabled by default. All caller inputs are
    validated before the first GET; any cursor drift aborts further requests.
    """
    account = getattr(adapter, "_account", None)
    if type(account) is not str or _ACCOUNT.fullmatch(account) is None:
        raise ValueError("Invalid practice account identity")
    windows = _windows(first_id, last_id)
    pinned = _id(snapshot_last_id, "pinned snapshot cursor")
    if pinned < int(last_id):
        raise ValueError("Snapshot cursor precedes requested history")
    if type(max_requests) is not int or not 1 <= max_requests <= _MAX_WINDOWS:
        raise ValueError("Invalid read-only request budget")
    if len(windows) > max_requests:
        raise ValueError("Read-only request budget exceeded")
    if (not isinstance(as_of, datetime) or as_of.tzinfo is None
            or as_of.utcoffset() is None):
        raise ValueError("Timezone-aware audit cutoff required")
    if (expected_census_sha256 is not None and
            (type(expected_census_sha256) is not str or
             _SHA.fullmatch(expected_census_sha256) is None)):
        raise ValueError("Invalid expected census fingerprint")
    from app.oanda_practice_transaction_range import read_practice_transaction_range

    reports = []
    for start, end in windows:
        report = read_practice_transaction_range(adapter, start, end, as_of=as_of)
        if (type(report) is not dict or
                report.get("broker_reported_latest_id") != snapshot_last_id):
            raise ValueError("Practice snapshot cursor drift; stop reading")
        reports.append(report)
    return audit_practice_transaction_windows(
        reports, account_id=account, first_id=first_id, last_id=last_id,
        snapshot_last_id=snapshot_last_id,
        expected_census_sha256=expected_census_sha256,
    )
