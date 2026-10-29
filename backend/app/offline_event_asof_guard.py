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


def audit_declared_event_window(revisions, *, decision_utc, source_id,
                                before_minutes=30, after_minutes=15):
    """Research-only, as-of event proximity census; never a trade clearance.

    Uses only schedules visible before the decision minute. Unknown events,
    omitted sources, incomplete calendars and unauthenticated receipts cannot
    be interpreted as proof that a market is safe to trade.
    """
    for name, value in (("before_minutes", before_minutes),
                        ("after_minutes", after_minutes)):
        if type(value) is not int or not 0 <= value <= 1440:
            raise ValueError(f"{name} must be an integer from 0 to 1440")
    snapshot = audit_declared_event_asof(
        revisions, decision_utc=decision_utc, source_id=source_id
    )
    cutoff = _utc(decision_utc)
    matches = []
    for event in snapshot["events"]:
        scheduled = _utc(event["scheduled_utc"])
        delta = int((scheduled - cutoff).total_seconds() // 60)
        if -after_minutes <= delta <= before_minutes:
            matches.append({
                "event_id": event["event_id"],
                "scheduled_utc": event["scheduled_utc"],
                "minutes_until_event": delta,
            })
    matches.sort(key=lambda x: (x["minutes_until_event"], x["event_id"]))
    envelope = {
        "schema_version": 1,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "before_minutes": before_minutes,
        "after_minutes": after_minutes,
        "matched_events": matches,
    }
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {
        "research_only": True,
        "trade_authorized": False,
        "authenticated_calendar": False,
        "coverage_verified": False,
        "decision_utc": snapshot["decision_utc"],
        "source_id": snapshot["source_id"],
        "before_minutes": before_minutes,
        "after_minutes": after_minutes,
        "visible_event_count": snapshot["visible_event_count"],
        "matched_event_count": len(matches),
        "within_declared_event_window": bool(matches),
        "matched_events": matches,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "window_audit_schema_version": 1,
        "window_audit_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
    }


def audit_declared_surprise_asof(revisions, *, decision_utc, source_id):
    """Compute declared raw actual-minus-forecast only when both are visible.

    A raw difference has no standardized units, surprise significance, or
    trade direction. This offline audit never grants execution permission.
    """
    from decimal import localcontext

    snapshot = audit_declared_event_asof(
        revisions, decision_utc=decision_utc, source_id=source_id
    )
    observations = []
    for event in snapshot["events"]:
        actual, forecast = event["actual"], event["forecast"]
        if actual is None:
            status, difference = "ACTUAL_NOT_VISIBLE", None
        elif forecast is None:
            status, difference = "FORECAST_MISSING", None
        else:
            # Both normalized inputs have bounded exponent and magnitude.
            # The default 28-digit context would round a 30-place surprise.
            with localcontext() as ctx:
                ctx.prec = 128
                raw = Decimal(actual) - Decimal(forecast)
                difference = format(raw, "f")
                if "." in difference:
                    difference = difference.rstrip("0").rstrip(".")
                if raw.is_zero():
                    difference = "0"
            status = "DECLARED_RAW_DIFFERENCE"
        observations.append({
            "event_id": event["event_id"],
            "revision": event["revision"],
            "scheduled_utc": event["scheduled_utc"],
            "forecast": forecast,
            "actual": actual,
            "status": status,
            "raw_actual_minus_forecast": difference,
        })
    envelope = {
        "schema_version": 1,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "observations": observations,
    }
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {
        "research_only": True,
        "trade_authorized": False,
        "authenticated_calendar": False,
        "coverage_verified": False,
        "comparable_units_verified": False,
        "source_id": snapshot["source_id"],
        "decision_utc": snapshot["decision_utc"],
        "visible_event_count": snapshot["visible_event_count"],
        "declared_difference_count": sum(
            item["status"] == "DECLARED_RAW_DIFFERENCE" for item in observations
        ),
        "observations": observations,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "surprise_audit_schema_version": 1,
        "surprise_audit_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }



def audit_declared_result_corrections_asof(revisions, *, decision_utc, source_id):
    """Research-only first visible result versus later as-of corrections.

    Only result receipts strictly before the decision minute are eligible.
    This is a declared-data audit, not a verified economic feed or signal.
    """
    from decimal import localcontext

    snapshot = audit_declared_event_asof(
        revisions, decision_utc=decision_utc, source_id=source_id
    )
    cutoff = _utc(decision_utc)

    def difference(left, right):
        if left is None or right is None:
            return None
        with localcontext() as ctx:
            ctx.prec = 128
            delta = Decimal(left) - Decimal(right)
            if delta.is_zero():
                return "0"
            formatted = format(delta, "f")
            return formatted.rstrip("0").rstrip(".") if "." in formatted else formatted

    visible = {}
    for entry in revisions:
        if entry["kind"] == "result" and _utc(entry["observed_utc"]) < cutoff:
            visible.setdefault(entry["event_id"], []).append(entry)

    observations = []
    for event in snapshot["events"]:
        results = sorted(visible.get(event["event_id"], []),
                         key=lambda entry: entry["revision"])
        if not results:
            observations.append({
                "event_id": event["event_id"], "status": "NO_VISIBLE_RESULT",
                "first_result_revision": None, "latest_result_revision": None,
                "first_result_observed_utc": None, "latest_result_observed_utc": None,
                "first_actual": None, "latest_actual": None,
                "first_surprise": None, "latest_surprise": None,
                "net_actual_change": None, "visible_result_revision_count": 0,
                "changed_result_revision_count": 0,
            })
            continue
        actuals = [_decimal(entry["actual"]) for entry in results]
        changed_count = sum(a != b for a, b in zip(actuals, actuals[1:]))
        observations.append({
            "event_id": event["event_id"],
            "status": "FIRST_RESULT_ONLY" if len(results) == 1 else "RESULT_REVISED",
            "first_result_revision": results[0]["revision"],
            "latest_result_revision": results[-1]["revision"],
            "first_result_observed_utc": _utc(results[0]["observed_utc"]).isoformat(),
            "latest_result_observed_utc": _utc(results[-1]["observed_utc"]).isoformat(),
            "first_actual": actuals[0], "latest_actual": actuals[-1],
            "first_surprise": difference(actuals[0], event["forecast"]),
            "latest_surprise": difference(actuals[-1], event["forecast"]),
            "net_actual_change": (
                difference(actuals[-1], actuals[0]) if len(results) > 1 else None
            ),
            "visible_result_revision_count": len(results),
            "changed_result_revision_count": changed_count,
        })

    envelope = {
        "schema_version": 1,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "observations": observations,
    }
    canonical = json.dumps(
        envelope, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return {
        "research_only": True, "trade_authorized": False,
        "authenticated_calendar": False, "coverage_verified": False,
        "comparable_units_verified": False,
        "source_id": snapshot["source_id"], "decision_utc": snapshot["decision_utc"],
        "visible_event_count": snapshot["visible_event_count"],
        "visible_result_event_count": sum(
            item["visible_result_revision_count"] > 0 for item in observations
        ),
        "revised_result_event_count": sum(
            item["visible_result_revision_count"] > 1 for item in observations
        ),
        "observations": observations,
        "research_envelope_v2_sha256": snapshot["research_envelope_v2_sha256"],
        "result_correction_audit_schema_version": 1,
        "result_correction_audit_sha256": hashlib.sha256(
            canonical.encode("utf-8")
        ).hexdigest(),
    }
