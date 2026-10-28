"""Disconnected, descriptive first-return / opposite-sweep event study.

This is NOT a news predictor, strategy backtest, or executable signal.
Caller-declared source-local M1 and event UTC identity remain unauthenticated.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation

_HORIZONS = (5, 15, 30, 60)
_MAX_CANDLES = 1_000_000
_MAX_EVENTS = 200


def _minute(value):
    if not isinstance(value, str):
        raise ValueError("Explicit UTC timestamp required")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Invalid UTC timestamp") from exc
    if (dt.tzinfo is None or dt.utcoffset() != timedelta(0) or
            dt.second != 0 or dt.microsecond != 0):
        raise ValueError("UTC minute-aligned timestamp required")
    return dt.astimezone(timezone.utc)


def _positive_price(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("Price must be decimal text or integer")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Invalid price") from exc
    if not result.is_finite() or result <= 0:
        raise ValueError("Finite positive price required")
    return result


def _fraction(numerator, denominator):
    if not denominator:
        return None
    return str((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.000001")))


def census_news_spike_reversal(candles, events, *, as_of_utc, source_id):
    """Observe first return-to-range and opposite-side sweeps after initial break.

    The first five M1 candles establish a one-sided break of the prior 15 M1
    range. At H minutes, outcomes are published only if every minute through H
    has completed and is present. Missing and pending are distinct; no
    missing outcome is imputed. All timestamps are M1 OPEN times in UTC.
    """
    if not isinstance(source_id, str) or not source_id.strip() or len(source_id) > 128:
        raise ValueError("Bounded source_id required")
    as_of = _minute(as_of_utc)
    if not isinstance(candles, (list, tuple)) or len(candles) > _MAX_CANDLES:
        raise ValueError("Bounded candle sequence required")
    if not isinstance(events, (list, tuple)) or len(events) > _MAX_EVENTS:
        raise ValueError("Bounded event sequence required")

    by_time = {}
    previous = None
    for candle in candles:
        if not isinstance(candle, dict) or set(candle) != {"time", "open", "high", "low", "close"}:
            raise ValueError("Closed-schema M1 candle required")
        at = _minute(candle["time"])
        if previous is not None and at <= previous:
            raise ValueError("Unsorted or duplicate M1 timestamp")
        previous = at
        if at + timedelta(minutes=1) > as_of:
            raise ValueError("Uncompleted M1 candle")
        o, h, l, c = (_positive_price(candle[k]) for k in ("open", "high", "low", "close"))
        if l > min(o, c) or h < max(o, c) or h < l:
            raise ValueError("Inconsistent OHLC")
        by_time[at] = (o, h, l, c)

    event_rows = []
    previous_event = None
    seen = set()
    for event in events:
        if not isinstance(event, dict) or set(event) != {"event_id", "time"}:
            raise ValueError("Closed-schema event required")
        name = event["event_id"]
        if not isinstance(name, str) or not name.strip() or len(name) > 128 or name in seen:
            raise ValueError("Unique bounded event_id required")
        seen.add(name)
        when = _minute(event["time"])
        if when > as_of or (previous_event is not None and when - previous_event < timedelta(minutes=75)):
            raise ValueError("Future, unsorted, or overlapping event window")
        previous_event = when
        base = {"event_id": name, "event_utc": when.isoformat(), "status": None,
                "initial_spike": None, "horizons": None}
        pre = [by_time.get(when + timedelta(minutes=i)) for i in range(-15, 0)]
        if any(bar is None for bar in pre):
            base["status"] = "missing_pre_event_minutes"
            event_rows.append(base)
            continue
        if as_of < when + timedelta(minutes=5):
            base["status"] = "pending_first_five_completion"
            event_rows.append(base)
            continue
        first = [by_time.get(when + timedelta(minutes=i)) for i in range(5)]
        if any(bar is None for bar in first):
            base["status"] = "missing_first_five_minutes"
            event_rows.append(base)
            continue
        upper, lower = max(bar[1] for bar in pre), min(bar[2] for bar in pre)
        up = any(bar[1] > upper for bar in first)
        down = any(bar[2] < lower for bar in first)
        direction = "both" if up and down else "up" if up else "down" if down else "none"
        base["initial_spike"] = direction
        if direction not in ("up", "down"):
            base["status"] = "non_directional_initial_spike"
            event_rows.append(base)
            continue
        base["status"] = "directional_initial_spike"
        first_break = next(i for i, bar in enumerate(first)
                           if (bar[1] > upper if direction == "up" else bar[2] < lower))
        horizons = {}
        for h in _HORIZONS:
            key = str(h)
            if as_of < when + timedelta(minutes=h):
                # A missing *already completed* minute cannot become available
                # merely by waiting for this later cumulative horizon to mature.
                # Future uncompleted minutes are not counted as missing.
                completed = int((as_of - when).total_seconds() // 60)
                known_gap = any(by_time.get(when + timedelta(minutes=i)) is None
                                for i in range(completed))
                horizons[key] = {"status": "missing_horizon_minutes" if known_gap else "pending_horizon",
                                 "first_return_minute": None,
                                 "first_opposite_sweep_minute": None}
                continue
            window = [by_time.get(when + timedelta(minutes=i)) for i in range(h)]
            if any(bar is None for bar in window):
                horizons[key] = {"status": "missing_horizon_minutes", "first_return_minute": None,
                                 "first_opposite_sweep_minute": None}
                continue
            first_return = None
            first_opposite = None
            for i in range(first_break, h):
                _, high, low, close = window[i]
                if first_return is None and lower <= close <= upper:
                    first_return = i + 1  # elapsed minutes at bar completion
                if first_opposite is None and (low < lower if direction == "up" else high > upper):
                    first_opposite = i + 1
            horizons[key] = {"status": "observed", "first_return_minute": first_return,
                             "first_opposite_sweep_minute": first_opposite}
        base["horizons"] = horizons
        event_rows.append(base)

    directional = [row for row in event_rows if row["status"] == "directional_initial_spike"]
    counts = {}
    for h in _HORIZONS:
        key = str(h)
        metrics = {}
        for metric, field in (("return_to_range", "first_return_minute"),
                              ("opposite_sweep", "first_opposite_sweep_minute")):
            yes = sum(row["horizons"][key]["status"] == "observed" and
                      row["horizons"][key][field] is not None for row in directional)
            no = sum(row["horizons"][key]["status"] == "observed" and
                     row["horizons"][key][field] is None for row in directional)
            pending = sum(row["horizons"][key]["status"] == "pending_horizon" for row in directional)
            missing = sum(row["horizons"][key]["status"] == "missing_horizon_minutes" for row in directional)
            n = len(directional)
            metrics[metric] = {"yes": yes, "no": no, "pending": pending, "missing": missing,
                               "eligible": n, "observed_fraction": _fraction(yes, yes + no),
                               "all_eligible_lower_bound": _fraction(yes, n),
                               "all_eligible_upper_bound": _fraction(yes + pending + missing, n)}
        counts[key] = metrics
    return {"research_only": True, "source_id": source_id, "as_of_utc": as_of.isoformat(),
            "pre_minutes": 15, "first_reaction_minutes": 5,
            "event_count": len(event_rows), "directional_eligible": len(directional),
            "events": event_rows, "horizons": counts}
