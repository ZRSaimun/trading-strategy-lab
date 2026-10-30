"""Offline explicit UTC session/closure manifest for completed M1 receipt review.

An operator-supplied schedule is NOT an authenticated exchange calendar. No
network, database, broker execution, live-data or entitlement assertion.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from app.prospective_receipt_census import audit_declared_m1_receipts

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ._:/-]{0,79}\Z")
_MAX_MINUTES = 10_000


@dataclass(frozen=True)
class ExpectedM1Manifest:
    provider: str
    symbol: str
    venue: str
    price_side: str
    calendar_id: str
    calendar_revision: str
    calendar_source: str
    observed_at_utc: int
    sessions_utc: tuple[tuple[int, int], ...]
    exclusions_utc: tuple[tuple[int, int], ...]
    expected_minutes: tuple[int, ...]
    manifest_sha256: str


def _intervals(values: object, name: str, observed_at_utc: int) -> tuple[tuple[int, int], ...]:
    if not isinstance(values, (tuple, list)) or len(values) > 100:
        raise ValueError(f"{name}: bounded UTC intervals required")
    result: list[tuple[int, int]] = []
    previous_end = -1
    for item in values:
        if not isinstance(item, (tuple, list)) or len(item) != 2:
            raise ValueError(f"{name}: UTC half-open pairs required")
        start, end = item
        if (type(start) is not int or type(end) is not int
                or start < 0 or start % 60 or end % 60
                or start >= end or end > observed_at_utc or start < previous_end):
            raise ValueError(f"{name}: ordered nonoverlapping completed UTC intervals required")
        result.append((start, end))
        previous_end = end
    return tuple(result)


def _fingerprint(data: dict) -> str:
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("utf-8")).hexdigest()


def _payload(m: ExpectedM1Manifest) -> dict:
    return {
        "provider": m.provider, "symbol": m.symbol, "venue": m.venue,
        "price_side": m.price_side, "calendar_id": m.calendar_id,
        "calendar_revision": m.calendar_revision, "calendar_source": m.calendar_source,
        "observed_at_utc": m.observed_at_utc,
        "sessions_utc": m.sessions_utc, "exclusions_utc": m.exclusions_utc,
        "expected_minutes": m.expected_minutes,
    }


def compile_expected_m1_manifest(
    *, provider: str, symbol: str, venue: str, price_side: str,
    calendar_id: str, calendar_revision: str, calendar_source: str,
    observed_at_utc: int, sessions_utc: list[tuple[int, int]],
    exclusions_utc: list[tuple[int, int]],
) -> ExpectedM1Manifest:
    """Compile only independently sourced, explicitly enumerated UTC sessions.

    Exclusions represent operator-declared full-minute closures, not inferred
    missing bars. Calendar provenance must be verified outside this function.
    """
    identifiers = (provider, symbol, venue, price_side, calendar_id,
                   calendar_revision, calendar_source)
    if any(not isinstance(x, str) or not _ID.fullmatch(x) for x in identifiers):
        raise ValueError("Exact bounded identity and calendar provenance required")
    if price_side not in ("BID", "ASK", "MID", "TRADE", "UNSPECIFIED"):
        raise ValueError("Unsupported price side")
    if type(observed_at_utc) is not int or not 60 <= observed_at_utc <= 253402300799:
        raise ValueError("Invalid server observation time")
    sessions = _intervals(sessions_utc, "sessions", observed_at_utc)
    exclusions = _intervals(exclusions_utc, "exclusions", observed_at_utc)
    if not sessions:
        raise ValueError("No completed session intervals; do not infer open market")
    total = sum((end - start) // 60 for start, end in sessions)
    if total > _MAX_MINUTES:
        raise ValueError("Session population exceeds bounded review limit")

    # Closures must be wholly contained within one declared open session.
    # Reject arbitrary excluded missing minutes and exclusion spans across breaks.
    for a, b in exclusions:
        if not any(start <= a < b <= end for start, end in sessions):
            raise ValueError("Exclusion outside a single declared session")
    excluded = {t for a, b in exclusions for t in range(a, b, 60)}
    expected = tuple(t for a, b in sessions for t in range(a, b, 60) if t not in excluded)
    if not expected:
        raise ValueError("Empty expected completed-bar population")

    preliminary = ExpectedM1Manifest(
        provider, symbol, venue, price_side, calendar_id, calendar_revision,
        calendar_source, observed_at_utc, sessions, exclusions, expected, "")
    return ExpectedM1Manifest(
        provider, symbol, venue, price_side, calendar_id, calendar_revision,
        calendar_source, observed_at_utc, sessions, exclusions, expected,
        _fingerprint(_payload(preliminary)),
    )


def audit_m1_receipts_against_manifest(
    receipts: list[dict], manifest: ExpectedM1Manifest, **limits: int
) -> dict:
    """Run the existing fail-closed receipt census against a frozen manifest."""
    if set(limits) - {"max_receipt_lag_seconds", "max_observation_age_seconds",
                       "max_expected_close_age_seconds", "sample_limit"}:
        raise ValueError("Unsupported receipt audit option")
    if type(manifest) is not ExpectedM1Manifest:
        raise ValueError("Compiled manifest required")
    rebuilt = compile_expected_m1_manifest(
        provider=manifest.provider, symbol=manifest.symbol, venue=manifest.venue,
        price_side=manifest.price_side, calendar_id=manifest.calendar_id,
        calendar_revision=manifest.calendar_revision, calendar_source=manifest.calendar_source,
        observed_at_utc=manifest.observed_at_utc,
        sessions_utc=list(manifest.sessions_utc),
        exclusions_utc=list(manifest.exclusions_utc),
    )
    if rebuilt != manifest:
        raise ValueError("Manifest changed after compilation")
    report = audit_declared_m1_receipts(
        receipts, list(manifest.expected_minutes), provider=manifest.provider,
        symbol=manifest.symbol, venue=manifest.venue, price_side=manifest.price_side,
        observed_at_utc=manifest.observed_at_utc, **limits)
    report["calendar_manifest_sha256"] = manifest.manifest_sha256
    report["calendar_id"] = manifest.calendar_id
    report["calendar_revision"] = manifest.calendar_revision
    report["calendar_source_declared"] = manifest.calendar_source
    report["declared_session_intervals"] = len(manifest.sessions_utc)
    report["declared_excluded_minutes"] = sum(
        (b - a) // 60 for a, b in manifest.exclusions_utc)
    # A fingerprint and provenance string do not establish independent calendar
    # verification or provider authentication.
    report["expected_calendar_verified"] = False
    report["live"] = False
    report["may_execute_order"] = False
    return report
