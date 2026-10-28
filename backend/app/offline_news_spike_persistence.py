"""Offline, read-only news-spike persistence census; not a trade or causal study.

Caller-declared UTC event timestamps and complete source-isolated M1 OHLC are
required. The first five post-event minutes classify the *observed* spike;
subsequent horizons describe persistence, never pre-event predictions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

_HORIZONS = (5, 15, 30, 60)
_MAX_BARS = 1_000_000
_MAX_EVENTS = 200


def _utc_minute(value):
    if not isinstance(value, str):
        raise ValueError("Timestamp must be an explicit UTC ISO-8601 string")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid timestamp") from exc
    if (dt.tzinfo is None or dt.utcoffset() != timedelta(0) or
            dt.second or dt.microsecond):
        raise ValueError("Expected UTC minute-aligned timestamp")
    return dt.astimezone(timezone.utc)


def _price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Prices must be finite decimal text or integers")
    try:
        price = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid price") from exc
    if not price.is_finite() or price <= 0:
        raise ValueError("Prices must be finite and positive")
    return price


def census_news_spike_persistence(candles, events, *, as_of_utc, source_id):
    """Return deterministic, non-executable descriptive event observations.

    All M1 candles are open-time stamped; one is complete only at open+1m.
    Missing minutes yield null horizon observations, never inferred prices.
    No market-side, vendor, event identity, licensing or UTC mapping is verified.
    """
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 128:
        raise ValueError("Explicit bounded source identity required")
    as_of = _utc_minute(as_of_utc)
    if not isinstance(candles, (list, tuple)) or len(candles) > _MAX_BARS:
        raise ValueError("Bounded candle list required")
    if not isinstance(events, (list, tuple)) or len(events) > _MAX_EVENTS:
        raise ValueError("Bounded event list required")
    by_time = {}
    previous = None
    for row in candles:
        if not isinstance(row, dict):
            raise ValueError("Invalid candle")
        ts = _utc_minute(row.get("time"))
        if previous is not None and ts <= previous:
            raise ValueError("Unsorted or duplicate candle timestamps")
        previous = ts
        if ts + timedelta(minutes=1) > as_of:
            raise ValueError("Uncompleted/future candle in input")
        o, h, l, c = (_price(row.get(key)) for key in ("open", "high", "low", "close"))
        if l > min(o, c) or h < max(o, c) or h < l:
            raise ValueError("Inconsistent OHLC")
        by_time[ts] = (o, h, l, c)

    output = []
    previous_event = None
    seen_ids = set()
    for event in events:
        if not isinstance(event, dict):
            raise ValueError("Invalid event")
        name = event.get("event_id")
        if (not isinstance(name, str) or not name.strip() or len(name) > 128 or
                name in seen_ids):
            raise ValueError("Unique bounded event ID required")
        seen_ids.add(name)
        when = _utc_minute(event.get("time"))
        if when > as_of:
            raise ValueError("Future event")
        # Disjoint complete study windows prevent double counting one M1 bar.
        if previous_event is not None and when - previous_event < timedelta(minutes=75):
            raise ValueError("Events must be sorted and >=75 minutes apart")
        previous_event = when
        pre = [by_time.get(when + timedelta(minutes=i)) for i in range(-15, 0)]
        if any(v is None for v in pre):
            output.append({"event_id": name, "event_utc": when.isoformat(),
                           "status": "missing_pre_event_minutes", "spike": None,
                           "horizons": None})
            continue
        pre_high = max(x[1] for x in pre)
        pre_low = min(x[2] for x in pre)
        # Incomplete reaction windows are pending, not observed data outages.
        if as_of < when + timedelta(minutes=5):
            output.append({"event_id": name, "event_utc": when.isoformat(),
                           "status": "pending_first_five_completion", "spike": None,
                           "horizons": None})
            continue
        first = [by_time.get(when + timedelta(minutes=i)) for i in range(5)]
        if any(v is None for v in first):
            output.append({"event_id": name, "event_utc": when.isoformat(),
                           "status": "missing_first_five_minutes", "spike": None,
                           "horizons": None})
            continue
        up = any(x[1] > pre_high for x in first)
        down = any(x[2] < pre_low for x in first)
        spike = "both" if up and down else "up" if up else "down" if down else "none"
        horizons = {}
        for minutes in _HORIZONS:
            # Require a complete contiguous post-event path, not only the last bar.
            window = [by_time.get(when + timedelta(minutes=i)) for i in range(minutes)]
            if any(v is None for v in window):
                horizons[str(minutes)] = {"status": "insufficient_complete_minutes",
                                          "position": None, "aligned": None}
                continue
            close = window[-1][3]
            position = ("above_pre_high" if close > pre_high else
                        "below_pre_low" if close < pre_low else "inside_pre_range")
            aligned = ((spike == "up" and position == "above_pre_high") or
                       (spike == "down" and position == "below_pre_low")) if spike in ("up", "down") else None
            horizons[str(minutes)] = {"status": "observed", "position": position,
                                      "aligned": aligned}
        output.append({"event_id": name, "event_utc": when.isoformat(),
                       "status": "observed", "spike": spike, "horizons": horizons})
    return {"research_only": True, "source_id": source_id,
            "as_of_utc": as_of.isoformat(), "pre_minutes": 15,
            "first_reaction_minutes": 5, "events": output}
