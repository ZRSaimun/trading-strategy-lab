"""Fail-closed, descriptive attrition audit of frozen news-spike census output.

No execution, forecasting, event authentication, or historical market data access.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

_HORIZONS = ("5", "15", "30", "60")
_DIRECTIONS = ("up", "down")
_SPIKES = ("up", "down", "both", "none")
_MISSING = ("missing_pre_event_minutes", "missing_first_five_minutes",
            "pending_first_five_completion")
_POSITIONS = ("above_pre_high", "below_pre_low", "inside_pre_range")


def _utc_minute(value):
    if not isinstance(value, str):
        raise ValueError("Explicit UTC minute required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset() != timedelta(0) or dt.second or dt.microsecond:
        raise ValueError("Explicit UTC minute required")
    return dt


def _exact(row, keys):
    if not isinstance(row, dict) or set(row) != set(keys):
        raise ValueError("Unexpected or missing census fields")


def _ratio(n, d):
    return str((Decimal(n) / Decimal(d)).quantize(Decimal("0.000001"))) if d else None


def audit_news_spike_attrition(report):
    """Count all event outcomes and unknown-horizon bounds without imputing returns.

    `report` is the unchanged output of `census_news_spike_persistence`.
    Source identity and calendar authenticity are *not* established by this audit.
    """
    _exact(report, ("research_only", "source_id", "as_of_utc", "pre_minutes",
                    "first_reaction_minutes", "events"))
    if report["research_only"] is not True or type(report["pre_minutes"]) is not int or report["pre_minutes"] != 15 or type(report["first_reaction_minutes"]) is not int or report["first_reaction_minutes"] != 5:
        raise ValueError("Unexpected census methodology")
    source = report["source_id"]
    if not isinstance(source, str) or not source.strip() or len(source) > 128:
        raise ValueError("Invalid source identity")
    as_of = _utc_minute(report["as_of_utc"])
    events = report["events"]
    if not isinstance(events, list) or len(events) > 200:
        raise ValueError("Bounded event list required")
    populations = {s: 0 for s in (*_SPIKES, *_MISSING)}
    rows = {s: {h: {"aligned": 0, "not_aligned": 0, "unknown": 0} for h in _HORIZONS}
            for s in (*_DIRECTIONS, "directional_total")}
    previous = None
    seen = set()
    for event in events:
        _exact(event, ("event_id", "event_utc", "status", "spike", "horizons"))
        event_id = event["event_id"]
        if not isinstance(event_id, str) or not event_id.strip() or len(event_id) > 128 or event_id in seen:
            raise ValueError("Invalid or duplicate event identity")
        seen.add(event_id)
        at = _utc_minute(event["event_utc"])
        if at > as_of or (previous is not None and at - previous < timedelta(minutes=75)):
            raise ValueError("Future, unsorted or overlapping event")
        previous = at
        status = event["status"]
        spike = event["spike"]
        horizons = event["horizons"]
        if status in _MISSING:
            if spike is not None or horizons is not None:
                raise ValueError("Quarantined event has fabricated outcome")
            mature = at + timedelta(minutes=5) <= as_of
            if (status == "pending_first_five_completion" and mature) or (status == "missing_first_five_minutes" and not mature):
                raise ValueError("First-five status contradicts completion cutoff")
            populations[status] += 1
            continue
        if status != "observed" or spike not in _SPIKES:
            raise ValueError("Unexpected event status or spike")
        if at + timedelta(minutes=5) > as_of:
            raise ValueError("Observed spike precedes first-five completion")
        populations[spike] += 1
        if not isinstance(horizons, dict) or set(horizons) != set(_HORIZONS):
            raise ValueError("Incomplete horizon census")
        prior_missing = False
        for h in _HORIZONS:
            row = horizons[h]
            _exact(row, ("status", "position", "aligned"))
            hstatus, position, aligned = row["status"], row["position"], row["aligned"]
            if hstatus == "insufficient_complete_minutes":
                if position is not None or aligned is not None:
                    raise ValueError("Missing horizon has invented outcome")
                prior_missing = True
                outcome = "unknown"
            elif hstatus == "observed":
                if prior_missing or at + timedelta(minutes=int(h)) > as_of:
                    raise ValueError("Noncausal or inconsistent horizon completeness")
                if position not in _POSITIONS:
                    raise ValueError("Invalid horizon position")
                expected = ((spike == "up" and position == "above_pre_high") or
                            (spike == "down" and position == "below_pre_low")) if spike in _DIRECTIONS else None
                if aligned is not expected:
                    raise ValueError("Incorrect directional alignment")
                outcome = "aligned" if aligned else "not_aligned"
            else:
                raise ValueError("Invalid horizon status")
            if spike in _DIRECTIONS:
                rows[spike][h][outcome] += 1
                rows["directional_total"][h][outcome] += 1
    total = len(events)
    directional = populations["up"] + populations["down"]
    results = {}
    for direction, hrows in rows.items():
        denominator = directional if direction == "directional_total" else populations[direction]
        results[direction] = {}
        for h, counts in hrows.items():
            observed = counts["aligned"] + counts["not_aligned"]
            unknown = counts["unknown"]
            if observed + unknown != denominator:
                raise ValueError("Directional population does not reconcile")
            results[direction][h] = {
                **counts, "eligible": denominator, "observed": observed,
                "observed_alignment_fraction": _ratio(counts["aligned"], observed),
                "all_eligible_lower_bound": _ratio(counts["aligned"], denominator),
                "all_eligible_upper_bound": _ratio(counts["aligned"] + unknown, denominator),
            }
    return {"research_only": True, "source_id": source, "as_of_utc": as_of.isoformat(),
            "event_count": total, "event_populations": populations,
            "directional_eligible": directional, "horizons": results,
            "meaning": "Descriptive alignment fractions and unknown-outcome bounds; not forecasts, trades or executable returns"}
