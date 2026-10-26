"""Pure formatter for UNVERIFIED forecast-review rehearsal messages.

No network, database, clock lookup, scheduler, quote, paper fill or order path.
Never pass its output off as an authenticated live signal or delivery receipt.
"""
from datetime import datetime, timezone
import math
import re

_LABEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,79}\Z")
_FEED = {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}
_MAX_EPOCH = 253402300799


def _label(value):
    if type(value) is not str or not _LABEL.fullmatch(value):
        raise ValueError("Unsafe forecast review label")
    return value


def _time(value):
    if type(value) is not int or not 0 <= value <= _MAX_EPOCH:
        raise ValueError("Invalid forecast review timestamp")
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


def _probability_text(probability):
    """Never round a nonzero/nonunit probability into a displayed 0% or 100%."""
    percent = probability * 100
    if percent < 0.01:
        return "<0.01%"
    if percent > 99.99:
        return ">99.99%"
    return f"{percent:.2f}%"


def render_unverified_forecast_review(snapshot, outbox_view, *, forecast_id, as_of):
    """Render a bounded, explicitly non-tradable message from validated store views.

    Callers must load the snapshot from ForecastEventStore.load and the view
    from ForecastAlertOutbox.read. This formatter does NOT authenticate either
    input; its output is always unverified and never authorizes a send.
    """
    _label(forecast_id)
    _time(as_of)
    if type(snapshot) is not dict or type(outbox_view) is not dict:
        raise ValueError("Missing forecast review views")
    if snapshot.get("evidence") != "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL":
        raise ValueError("Unexpected forecast review evidence")
    if any(outbox_view.get(k) is not False for k in (
        "sourceAuthenticated", "deliveryVerified", "notificationEnabled",
        "mayExecutePaperOrder", "mayExecuteLiveOrder"
    )):
        raise ValueError("Unsupported forecast review authority")
    identity = snapshot.get("identity")
    if type(identity) is not dict or set(identity) != _FEED:
        raise ValueError("Invalid forecast review feed")
    for key in ("instrument", "provider", "venue", "sourceId"):
        _label(identity[key])
    side = identity["priceSide"]
    seconds = identity["seconds"]
    if side not in ("bid", "ask", "mid") or type(side) is not str or \
            type(seconds) is not int or not 60 <= seconds <= 86400 or seconds % 60:
        raise ValueError("Invalid forecast review candle identity")
    if outbox_view.get("forecastId") != forecast_id or \
            outbox_view.get("status") not in ("QUEUED", "IN_FLIGHT_UNCERTAIN"):
        raise ValueError("Forecast review outbox not eligible")
    expiry = outbox_view.get("expiresAt")
    _time(expiry)
    if as_of >= expiry:
        raise ValueError("Forecast review expired")
    if type(snapshot.get("events")) is not list or type(snapshot.get("forecasts")) is not list:
        raise ValueError("Missing forecast review journal")
    forecasts = [f for f in snapshot["forecasts"] if type(f) is dict and f.get("id") == forecast_id]
    events = [e for e in snapshot["events"] if type(e) is dict and e.get("kind") == "FORECAST"
              and e.get("id") == forecast_id]
    if len(forecasts) != 1 or len(events) != 1:
        raise ValueError("Forecast review linkage missing or duplicate")
    row, event = forecasts[0], events[0]
    horizon, probability = row.get("horizon"), row.get("probability")
    if row.get("status") != "PENDING" or type(horizon) is not int or horizon not in (1, 3, 12) or \
            type(probability) not in (int, float) or not math.isfinite(probability) or \
            not 0 < probability < 1 or row.get("outcomeUp") is not None or \
            row.get("resolvedAt") is not None:
        raise ValueError("Forecast review is not an unresolved probability")
    model = _label(row.get("modelVersion"))
    base, target, issued = row.get("baseStart"), row.get("targetStart"), row.get("issuedAt")
    _time(base)
    _time(target)
    _time(issued)
    if target != base + horizon * seconds or base % seconds or issued > as_of or \
            issued < base + seconds or as_of >= target + seconds or\
            expiry > target + seconds:
        raise ValueError("Forecast review chronology invalid")
    if (event.get("seq") != outbox_view.get("issueSeq") or
            event.get("modelVersion") != model or event.get("horizon") != horizon or
            event.get("probability") != probability or event.get("baseStart") != base or
            event.get("receivedAt") != issued):
        raise ValueError("Forecast review event/outbox mismatch")
    message = (
        "UNVERIFIED RESEARCH FORECAST - NOT LIVE / NOT A TRADE\n"
        f"Instrument: {identity['instrument']}\n"
        f"Source: {identity['provider']} / {identity['venue']} / {identity['sourceId']}\n"
        f"Candle: {seconds // 60}m {side.upper()} (NOT an executable quote)\n"
        f"Model: {model}; horizon: {horizon} completed candles\n"
        f"P(up vs base close): {_probability_text(probability)} (UNCALIBRATED)\n"
        f"Base UTC: {_time(base)}\n"
        f"Target closes UTC: {_time(target + seconds)}\n"
        f"Issued UTC: {_time(issued)}; expires UTC: {_time(expiry)}\n"
        "Source NOT authenticated; no broker BID/ASK or fill. "
        "NO BUY/SELL SIGNAL. NO PAPER OR LIVE ORDER."
    )
    if len(message) > 1000:
        raise ValueError("Forecast review message exceeds transport bound")
    return message
