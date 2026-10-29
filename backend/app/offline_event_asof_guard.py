"""Offline as-of gate for declared economic-calendar revisions.

This does not authenticate a calendar, feed, publication clock, or trade.
Only observations visible at a historical decision cutoff can be returned.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

_MAX = 5000
_KEYS = {"event_id", "revision", "kind", "scheduled_utc", "published_utc",
         "observed_utc", "forecast", "actual"}


def _utc(value):
    if not isinstance(value, str):
        raise ValueError("Explicit UTC minute timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0) or dt.second or dt.microsecond:
        raise ValueError("UTC minute-aligned timestamp required")
    return dt.astimezone(timezone.utc)


def _decimal(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 80:
        raise ValueError("Economic value must be bounded decimal text")
    try:
        d = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid economic value") from exc
    if not d.is_finite() or d.copy_abs() > Decimal("1e30"):
        raise ValueError("Finite bounded economic value required")
    # Decimal.normalize() uses the ambient 28-digit context and can silently
    # round longer economic values. Preserve every accepted decimal digit.
    if not -30 <= d.as_tuple().exponent <= 30:
        raise ValueError("Bounded decimal exponent required")
    if d.is_zero():
        return "0"
    exact = format(d, "f")
    return exact.rstrip("0").rstrip(".") if "." in exact else exact


def audit_declared_event_asof(revisions, *, decision_utc, source_id):
    """Return eligible schedule revisions, suppress unavailable actuals.

    One immutable event identity can have consecutive revision numbers. Revisions
    must be ordered by first-observation time, and each must have a publication
    time no later than observation. Result values are only available once the
    event has occurred AND the result revision was observed by the cutoff.
    Later revisions cannot rewrite the earlier decision snapshot.
    Because receipt clocks are minute-granular, observations stamped in the
    decision minute are excluded: their within-minute order is unknown.
    """
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 128:
        raise ValueError("Bounded source identity required")
    cutoff = _utc(decision_utc)
    if not isinstance(revisions, (list, tuple)) or len(revisions) > _MAX:
        raise ValueError("Bounded revision sequence required")
    groups = {}
    for item in revisions:
        if not isinstance(item, dict) or set(item) != _KEYS:
            raise ValueError("Closed-schema revision required")
        eid = item["event_id"]
        rev = item["revision"]
        kind = item["kind"]
        if not isinstance(eid, str) or not eid.strip() or len(eid) > 128:
            raise ValueError("Bounded event identity required")
        if type(rev) is not int or rev < 1 or rev > _MAX or kind not in ("schedule", "result"):
            raise ValueError("Invalid revision number or kind")
        scheduled, published, observed = (_utc(item[k]) for k in
                                          ("scheduled_utc", "published_utc", "observed_utc"))
        if published > observed:
            raise ValueError("Observation cannot precede publication")
        forecast, actual = _decimal(item["forecast"]), _decimal(item["actual"])
        if kind == "schedule" and actual is not None:
            raise ValueError("Schedule revision cannot contain actual")
        if kind == "result" and (actual is None or published < scheduled or observed < scheduled):
            raise ValueError("Result requires actual and post-event release clocks")
        record = {"event_id": eid, "revision": rev, "kind": kind,
                  "scheduled_utc": scheduled.isoformat(),
                  "published_utc": published.isoformat(),
                  "observed_utc": observed.isoformat(),
                  "forecast": forecast, "actual": actual}
        groups.setdefault(eid, []).append(record)
    output = []
    for eid in sorted(groups):
        entries = groups[eid]
        entries.sort(key=lambda x: x["revision"])
        if entries[0]["revision"] != 1 or entries[0]["kind"] != "schedule":
            raise ValueError("First revision must be a schedule")
        previous = None
        seen_result = False
        last_schedule = None
        for idx, entry in enumerate(entries):
            if entry["revision"] != idx + 1:
                raise ValueError("Missing or duplicate revision")
            observed = _utc(entry["observed_utc"])
            if previous is not None and observed <= previous:
                raise ValueError("Revision observation clocks must increase")
            previous = observed
            if seen_result and entry["kind"] != "result":
                raise ValueError("Schedule revision after result forbidden")
            if entry["kind"] == "schedule":
                # A schedule/consensus must be observed strictly before its
                # own event time; post-release consensus is not pre-news data.
                if observed >= _utc(entry["scheduled_utc"]):
                    raise ValueError("Schedule must be observed before its event time")
                # Post-event postponements cannot retroactively erase the
                # originally scheduled release. Fail closed until modeled.
                if last_schedule is not None and observed >= _utc(last_schedule["scheduled_utc"]):
                    raise ValueError("Schedule revision observed at or after prior event time")
                last_schedule = entry
            elif (entry["scheduled_utc"] != last_schedule["scheduled_utc"]
                  or entry["forecast"] != last_schedule["forecast"]):
                # A post-release record must not rewrite the pre-release
                # schedule or forecast used to measure economic surprise.
                raise ValueError("Result must match latest schedule and forecast")
            seen_result |= entry["kind"] == "result"
        eligible = [e for e in entries if _utc(e["observed_utc"]) < cutoff]
        if not eligible:
            continue
        latest = eligible[-1]
        # Never reveal a result before its declared event time.
        actual = latest["actual"] if latest["kind"] == "result" and _utc(latest["scheduled_utc"]) <= cutoff else None
        output.append({"event_id": eid, "revision": latest["revision"],
                       "scheduled_utc": latest["scheduled_utc"],
                       "forecast": latest["forecast"], "actual": actual,
                       "result_available": actual is not None})
    canonical = json.dumps(output, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    # The legacy snapshot digest intentionally identifies only visible event
    # content. A separate, versioned research envelope binds declared source,
    # decision cutoff and visible revision population so identical event lists
    # from different sources or cutoffs cannot be mistaken for the same audit.
    # The v1 envelope records only the final visible event per identity and
    # a revision count. Distinct visible revision histories can therefore have
    # the same v1 hash. Preserve v1 for consumers and provide a new opt-in
    # history-bound envelope without exposing future (invisible) revisions.
    visible_history = [
        entry for eid in sorted(groups) for entry in groups[eid]
        if _utc(entry["observed_utc"]) < cutoff
    ]
    visible_count = len(visible_history)
    history_canonical = json.dumps(
        visible_history, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    history_sha256 = hashlib.sha256(history_canonical.encode("utf-8")).hexdigest()
    envelope = {
        "schema_version": 1,
        "source_id": source_id,
        "decision_utc": cutoff.isoformat(),
        "visible_revision_count": visible_count,
        "events": output,
    }
    envelope_canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    envelope_v2 = {
        "schema_version": 2,
        "source_id": source_id,
        "decision_utc": cutoff.isoformat(),
        "visible_revision_count": visible_count,
        "visible_revision_history_sha256": history_sha256,
        "events": output,
    }
    envelope_v2_canonical = json.dumps(
        envelope_v2, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {"research_only": True, "authenticated_calendar": False,
            "trade_authorized": False, "source_id": source_id,
            "decision_utc": cutoff.isoformat(), "visible_revision_count": visible_count,
            "visible_event_count": len(output), "events": output,
            "visible_snapshot_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
            "research_envelope_schema_version": 1,
            "research_envelope_sha256": hashlib.sha256(
                envelope_canonical.encode("utf-8")
            ).hexdigest(),
            "visible_revision_history_sha256": history_sha256,
            "research_envelope_v2_schema_version": 2,
            "research_envelope_v2_sha256": hashlib.sha256(
                envelope_v2_canonical.encode("utf-8")
            ).hexdigest()}
