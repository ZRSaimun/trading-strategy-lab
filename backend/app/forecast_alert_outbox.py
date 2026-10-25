"""Disconnected durable forecast-review outbox; NEVER a notification sender.

A claim is irrevocably uncertain until independently reconciled. This module
has no network transport, credentials, market feed or broker-order capability.
"""
import hashlib
import json
import secrets
import time

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .db import Audit, Record, Session
from .forecast_event_store import ForecastEventStore, _feed, _ID, _epoch, _strict_loads

MAX_DOCUMENT_BYTES = 8192
_STATES = {"QUEUED", "IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED", "CANCELLED"}


class ForecastAlertOutbox:
    def __init__(self, session_factory=Session, clock=None):
        self.session_factory = session_factory
        self.clock = clock or (lambda: int(time.time()))

    def _now(self):
        now = self.clock()
        if not _epoch(now):
            raise ValueError("Invalid outbox server clock")
        return now

    @staticmethod
    def _key(session_id, forecast_id):
        ForecastEventStore._key(session_id)
        if type(forecast_id) is not str or not _ID.fullmatch(forecast_id):
            raise ValueError("Invalid forecast alert ID")
        token = f"{session_id}:{forecast_id}".encode("ascii")
        return "forecast-alert:" + hashlib.sha256(token).hexdigest()

    @staticmethod
    def _pack(state):
        raw = json.dumps(state, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(raw.encode()) > MAX_DOCUMENT_BYTES:
            raise ValueError("Outbox document exceeds size limit")
        return json.dumps({"payload": raw, "sha256": hashlib.sha256(raw.encode()).hexdigest()},
                          sort_keys=True, separators=(",", ":"))

    @staticmethod
    def _unpack(raw, now):
        try:
            if type(raw) is not str or len(raw.encode()) > 2 * MAX_DOCUMENT_BYTES:
                raise ValueError("Oversized outbox envelope")
            envelope = _strict_loads(raw)
            if type(envelope) is not dict or set(envelope) != {"payload", "sha256"} or type(envelope["payload"]) is not str:
                raise ValueError("Malformed outbox envelope")
            encoded = envelope["payload"].encode()
            if len(encoded) > MAX_DOCUMENT_BYTES or hashlib.sha256(encoded).hexdigest() != envelope["sha256"]:
                raise ValueError("Outbox digest mismatch")
            state = _strict_loads(envelope["payload"])
            keys = {"version", "identity", "forecastId", "modelVersion", "horizon", "baseStart",
                    "issueSeq", "issuedAt", "expiresAt", "status", "claimId", "claimedAt", "ackAt"}
            if type(state) is not dict or set(state) != keys or type(state["version"]) is not int or state["version"] != 1:
                raise ValueError("Malformed outbox state")
            _feed(state["identity"])
            if any(type(state[k]) is not str or not _ID.fullmatch(state[k]) for k in ("forecastId", "modelVersion")):
                raise ValueError("Invalid forecast identity")
            if type(state["horizon"]) is not int or state["horizon"] not in (1, 3, 12) or                type(state["issueSeq"]) is not int or state["issueSeq"] < 1 or                not all(_epoch(state[k]) for k in ("baseStart", "issuedAt", "expiresAt")) or                state["issuedAt"] > state["expiresAt"] or state["issuedAt"] > now or                state["status"] not in _STATES:
                raise ValueError("Invalid outbox timestamps or status")
            if state["status"] in ("QUEUED", "CANCELLED"):
                if any(state[k] is not None for k in ("claimId", "claimedAt", "ackAt")):
                    raise ValueError("Invalid unclaimed outbox state")
            else:
                if type(state["claimId"]) is not str or len(state["claimId"]) != 32 or                    any(c not in "0123456789abcdef" for c in state["claimId"]) or                    not _epoch(state["claimedAt"]) or not state["issuedAt"] <= state["claimedAt"] <= now:
                    raise ValueError("Invalid outbox claim")
                if state["status"] == "IN_FLIGHT_UNCERTAIN" and state["ackAt"] is not None:
                    raise ValueError("Uncertain claim has ACK")
                if state["status"] == "ACK_RECORDED_UNVERIFIED" and (not _epoch(state["ackAt"]) or
                        not state["claimedAt"] <= state["ackAt"] <= now):
                    raise ValueError("Invalid outbox ACK")
            return state
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError("Outbox integrity failure; manual reconciliation required") from exc

    @staticmethod
    def _view(state, now):
        status = state["status"]
        if status == "QUEUED" and now >= state["expiresAt"]:
            status = "EXPIRED_UNCLAIMED"
        return {"status": status, "forecastId": state["forecastId"],
                "issueSeq": state["issueSeq"], "expiresAt": state["expiresAt"],
                "claimId": state["claimId"], "sourceAuthenticated": False,
                "deliveryVerified": False, "notificationEnabled": False,
                "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False}

    def read(self, session_id, forecast_id):
        key, now = self._key(session_id, forecast_id), self._now()
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            return None if raw is None else self._view(self._unpack(raw, now), now)

    def queue(self, session_id, identity, forecast_id, max_age_seconds=300):
        """Enqueue only a persisted, unresolved prospective forecast.

        The journal is read in the same DB transaction as the queue insert, but
        source authenticity is NOT established by either record.
        """
        key, now = self._key(session_id, forecast_id), self._now()
        _feed(identity)
        if type(max_age_seconds) is not int or not 1 <= max_age_seconds <= 3600:
            raise ValueError("Invalid forecast alert age budget")
        with self.session_factory() as db:
            journal_raw = db.scalar(select(Record.value).where(
                Record.key == ForecastEventStore._key(session_id)))
            if journal_raw is None:
                raise ValueError("No persisted forecast journal")
            journal, forecasts = ForecastEventStore._unpack(journal_raw, now)
            if journal["identity"] != identity:
                raise ValueError("Forecast alert source mismatch")
            found = next((f for f in forecasts if f["id"] == forecast_id), None)
            event = next((e for e in journal["events"] if e["kind"] == "FORECAST" and e["id"] == forecast_id), None)
            if found is None or event is None or found["status"] != "PENDING":
                raise ValueError("Forecast is missing or no longer pending")
            expiry = min(event["receivedAt"] + max_age_seconds,
                         found["targetStart"] + identity["seconds"])
            if now >= expiry:
                raise ValueError("Forecast review alert expired")
            prior = db.scalar(select(Record.value).where(Record.key == key))
            if prior is not None:
                previous = self._unpack(prior, now)
                if previous["identity"] != identity or previous["issueSeq"] != event["seq"] or previous["forecastId"] != forecast_id:
                    raise ValueError("Conflicting existing outbox identity")
                return False
            state = {"version": 1, "identity": identity.copy(), "forecastId": forecast_id,
                     "modelVersion": event["modelVersion"], "horizon": event["horizon"],
                     "baseStart": event["baseStart"], "issueSeq": event["seq"],
                     "issuedAt": event["receivedAt"], "expiresAt": expiry,
                     "status": "QUEUED", "claimId": None, "claimedAt": None, "ackAt": None}
            try:
                db.execute(insert(Record).values(key=key, value=self._pack(state)))
                db.add(Audit(time=now, actor="system", action="forecast.alert.queue",
                             detail=json.dumps({"record": key, "issueSeq": event["seq"]})))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False  # Another worker won the unique-key insertion.

    def _transition(self, session_id, forecast_id, action, claim_id=None):
        key, now = self._key(session_id, forecast_id), self._now()
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                raise ValueError("Unknown forecast alert")
            state = self._unpack(raw, now)
            if action in ("claim", "cancel"):
                if state["status"] != "QUEUED" or now >= state["expiresAt"]:
                    return None
                if action == "claim":
                    # Revalidate the journal *at claim time*: a previously queued
                    # forecast can be voided by an intervening candle gap. Lock
                    # the journal row on PostgreSQL to order this read against
                    # concurrent forecast-settlement writes.
                    journal_raw = db.scalar(
                        select(Record.value).where(
                            Record.key == ForecastEventStore._key(session_id)
                        ).with_for_update()
                    )
                    if journal_raw is None:
                        raise ValueError("Forecast journal missing; alert claim denied")
                    journal, forecasts = ForecastEventStore._unpack(journal_raw, now)
                    forecast = next(
                        (f for f in forecasts if f["id"] == forecast_id), None
                    )
                    issued = next(
                        (e for e in journal["events"]
                         if e["kind"] == "FORECAST" and e["id"] == forecast_id), None
                    )
                    if (journal["identity"] != state["identity"]
                            or forecast is None or forecast["status"] != "PENDING"
                            or issued is None or issued["seq"] != state["issueSeq"]
                            or issued["modelVersion"] != state["modelVersion"]
                            or issued["horizon"] != state["horizon"]
                            or issued["baseStart"] != state["baseStart"]
                            or issued["receivedAt"] != state["issuedAt"]):
                        return None
                    state.update(status="IN_FLIGHT_UNCERTAIN", claimId=secrets.token_hex(16), claimedAt=now)
                else:
                    state["status"] = "CANCELLED"
            elif action == "ack":
                if state["status"] != "IN_FLIGHT_UNCERTAIN" or                    type(claim_id) is not str or claim_id != state["claimId"]:
                    return None
                state.update(status="ACK_RECORDED_UNVERIFIED", ackAt=now)
            else:
                raise ValueError("Invalid outbox transition")
            result = db.execute(update(Record).where(Record.key == key, Record.value == raw)
                                .values(value=self._pack(state)))
            if result.rowcount != 1:
                db.rollback()
                return None
            db.add(Audit(time=now, actor="system", action="forecast.alert." + action,
                         detail=json.dumps({"record": key, "status": state["status"]})))
            db.commit()
            return self._view(state, now)

    def claim(self, session_id, forecast_id):
        """Reserve once, before any external send; ambiguous claims never retry."""
        return self._transition(session_id, forecast_id, "claim")

    def acknowledge_unverified(self, session_id, forecast_id, claim_id):
        """Record a self-attested ACK; never claim provider-verified delivery."""
        return self._transition(session_id, forecast_id, "ack", claim_id)

    def cancel_unclaimed(self, session_id, forecast_id):
        return self._transition(session_id, forecast_id, "cancel")
