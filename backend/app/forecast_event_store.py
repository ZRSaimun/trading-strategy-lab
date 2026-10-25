"""Disconnected, transactional prospective forecast event journal.

No route, worker, feed, provider credentials, notification transport or broker is
installed. This is a server-side persistence primitive, not evidence of a live
forecast. Its clock is injected for tests; production must supply a server clock.
"""
import hashlib
import json
import math
import re
import time

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .db import Audit, Record, Session

MAX_EVENTS = 5000
MAX_BYTES = 2_000_000
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_HORIZONS = (1, 3, 12)
_FEED_KEYS = {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}


def _epoch(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _strict_loads(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate forecast JSON key")
            result[key] = value
        return result

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite forecast number")
        return result

    def invalid(_):
        raise ValueError("Nonfinite forecast number")

    return json.loads(raw, object_pairs_hook=unique, parse_float=finite_float,
                      parse_constant=invalid)


def _feed(identity):
    if type(identity) is not dict or set(identity) != _FEED_KEYS:
        raise ValueError("Invalid exact forecast feed identity")
    for key in ("instrument", "provider", "venue", "sourceId"):
        value = identity[key]
        if type(value) is not str or not 1 <= len(value) <= 160 or value != value.strip():
            raise ValueError("Invalid exact forecast feed identity")
    if identity["priceSide"] not in ("bid", "ask", "mid") or type(identity["priceSide"]) is not str:
        raise ValueError("Invalid forecast price side")
    seconds = identity["seconds"]
    if type(seconds) is not int or not 60 <= seconds <= 86400 or seconds % 60:
        raise ValueError("Invalid forecast candle duration")


def _number(value):
    return type(value) in (int, float) and math.isfinite(value)


def _replay(payload, as_of):
    """Validate every event and derive outcomes; never trust stored scores."""
    if type(payload) is not dict or set(payload) != {"version", "identity", "maxLagSeconds", "events"} or payload["version"] != 1:
        raise ValueError("Invalid forecast event document")
    identity = payload["identity"]
    _feed(identity)
    lag = payload["maxLagSeconds"]
    if type(lag) is not int or not 0 <= lag <= 3600:
        raise ValueError("Invalid forecast receipt lag")
    events = payload["events"]
    if type(events) is not list or len(events) > MAX_EVENTS:
        raise ValueError("Invalid forecast event count")
    last = None
    last_at = -1
    forecasts = {}
    issued = set()
    for seq, event in enumerate(events, start=1):
        if type(event) is not dict or event.get("seq") != seq or not _epoch(event.get("receivedAt")):
            raise ValueError("Missing or reordered forecast event")
        at = event["receivedAt"]
        if at < last_at or at > as_of:
            raise ValueError("Backward or future forecast receipt")
        last_at = at
        if event.get("kind") == "CANDLE":
            if set(event) != {"seq", "receivedAt", "kind", "start", "close"}:
                raise ValueError("Malformed completed-candle event")
            start, close = event["start"], event["close"]
            if not _epoch(start) or start % identity["seconds"] or not _number(close) or close <= 0:
                raise ValueError("Invalid completed candle")
            end = start + identity["seconds"]
            if not _epoch(end) or not end <= at <= end + lag:
                raise ValueError("Uncompleted, stale or future candle")
            if last is not None:
                if start <= last["start"]:
                    raise ValueError("Revised or backward completed candle")
                gap = start - last["start"] != identity["seconds"]
                for forecast in forecasts.values():
                    if forecast["status"] != "PENDING":
                        continue
                    if gap or forecast["targetStart"] < start:
                        forecast.update(status="VOID_GAP", resolvedAt=at, outcomeUp=None)
                    elif forecast["targetStart"] == start:
                        forecast.update(status="SETTLED", resolvedAt=at,
                                        outcomeUp=close > forecast["baseClose"])
            last = {"start": start, "close": close, "receivedAt": at}
        elif event.get("kind") == "FORECAST":
            if set(event) != {"seq", "receivedAt", "kind", "id", "modelVersion", "horizon", "probability", "baseStart"}:
                raise ValueError("Malformed forecast issuance event")
            fid, model, horizon, probability = (event[k] for k in ("id", "modelVersion", "horizon", "probability"))
            if type(fid) is not str or not _ID.fullmatch(fid) or fid in forecasts or \
               type(model) is not str or not _ID.fullmatch(model) or type(horizon) is not int or horizon not in _HORIZONS or \
               not _number(probability) or not 0 < probability < 1 or last is None:
                raise ValueError("Invalid or duplicate prospective forecast")
            if event["baseStart"] != last["start"]:
                raise ValueError("Forecast base was not latest observed candle")
            if not last["receivedAt"] <= at < last["start"] + 2 * identity["seconds"] or \
               at - (last["start"] + identity["seconds"]) > lag:
                raise ValueError("Retroactive or stale forecast issuance")
            unique = (model, horizon, last["start"])
            if unique in issued:
                raise ValueError("Duplicate model/bar/horizon forecast")
            issued.add(unique)
            target = last["start"] + horizon * identity["seconds"]
            if not _epoch(target + identity["seconds"]):
                raise ValueError("Forecast target overflows")
            forecasts[fid] = {"id": fid, "modelVersion": model, "horizon": horizon,
                              "probability": probability, "baseStart": last["start"],
                              "baseClose": last["close"], "issuedAt": at,
                              "targetStart": target, "status": "PENDING",
                              "resolvedAt": None, "outcomeUp": None}
        else:
            raise ValueError("Unsupported forecast event type")
    return list(forecasts.values())


class ForecastEventStore:
    """CAS append plus atomic audit using existing Record/Audit tables.

    A caller must authenticate and authorize its feed before using this class.
    No remote input is accepted directly; no broker orders or alerts are sent.
    """
    def __init__(self, session_factory=Session, clock=None):
        self.session_factory = session_factory
        self.clock = clock or (lambda: int(time.time()))

    @staticmethod
    def _key(session_id):
        if type(session_id) is not str or not _ID.fullmatch(session_id):
            raise ValueError("Invalid forecast session ID")
        return "forecast-events:" + hashlib.sha256(session_id.encode("ascii")).hexdigest()

    def _now(self):
        now = self.clock()
        if not _epoch(now):
            raise ValueError("Invalid server receipt clock")
        return now

    @staticmethod
    def _pack(payload):
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True, allow_nan=False)
        if len(raw.encode("utf-8")) > MAX_BYTES:
            raise ValueError("Forecast journal byte limit exceeded")
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        return json.dumps({"payload": raw, "sha256": digest}, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _unpack(raw, as_of):
        try:
            doc = _strict_loads(raw)
            if type(doc) is not dict or set(doc) != {"payload", "sha256"} or type(doc["payload"]) is not str:
                raise ValueError("Invalid forecast journal envelope")
            if len(doc["payload"].encode("utf-8")) > MAX_BYTES or \
               hashlib.sha256(doc["payload"].encode("utf-8")).hexdigest() != doc["sha256"]:
                raise ValueError("Forecast journal digest mismatch")
            payload = _strict_loads(doc["payload"])
            forecasts = _replay(payload, as_of)
            return payload, forecasts
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError("Stored forecast journal corrupt; manual reconciliation required") from exc

    def load(self, session_id):
        key, now = self._key(session_id), self._now()
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                return None
            payload, forecasts = self._unpack(raw, now)
            return {"sequence": len(payload["events"]), "identity": payload["identity"],
                    "maxLagSeconds": payload["maxLagSeconds"],
                    "events": payload["events"], "forecasts": forecasts,
                    "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}

    def append(self, session_id, identity, max_lag_seconds, expected_sequence, action):
        key, now = self._key(session_id), self._now()
        _feed(identity)
        if type(max_lag_seconds) is not int or not 0 <= max_lag_seconds <= 3600 or \
           type(expected_sequence) is not int or not 0 <= expected_sequence <= MAX_EVENTS:
            raise ValueError("Invalid forecast append bounds")
        if type(action) is not dict or "receivedAt" in action or "seq" in action or \
           action.get("kind") not in ("CANDLE", "FORECAST"):
            raise ValueError("Invalid or caller-timestamped forecast action")
        with self.session_factory() as db:
            try:
                old_raw = db.scalar(select(Record.value).where(Record.key == key))
                if old_raw is None:
                    payload = {"version": 1, "identity": identity.copy(),
                               "maxLagSeconds": max_lag_seconds, "events": []}
                    _replay(payload, now)
                else:
                    payload, _ = self._unpack(old_raw, now)
                    if payload["identity"] != identity or payload["maxLagSeconds"] != max_lag_seconds:
                        raise ValueError("Stored forecast source or lag identity mismatch")
                if len(payload["events"]) != expected_sequence:
                    return False
                event = {**action, "seq": expected_sequence + 1, "receivedAt": now}
                updated = {**payload, "events": [*payload["events"], event]}
                _replay(updated, now)
                packed = self._pack(updated)
                if old_raw is None:
                    db.execute(insert(Record).values(key=key, value=packed))
                else:
                    result = db.execute(update(Record).where(Record.key == key,
                                                           Record.value == old_raw).values(value=packed))
                    if result.rowcount != 1:
                        db.rollback()
                        return False
                db.add(Audit(time=now, actor="system", action="forecast.events.append",
                             detail=json.dumps({"session_hash": key.split(":", 1)[1],
                                                "sequence": expected_sequence + 1,
                                                "kind": action["kind"],
                                                "sha256": hashlib.sha256(packed.encode()).hexdigest()})))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                if old_raw is None:
                    return False
                raise
