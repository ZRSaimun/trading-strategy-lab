"""Opt-in, fail-closed, persistent PAPER-only risk reservations.

Not wired to an HTTP route, order sender, broker, or the paper fill journal.
A caller must authenticate the owner and reconcile terminal positions separately.
All account/order identifiers are hashed before persistence or audit logging.
"""
import hashlib
import json
import re
import time
from decimal import Decimal

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .db import Audit, Record, Session

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_CASH = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_MAX_RESERVATIONS = 500
# Hard bound on persisted envelopes before parsing untrusted/corrupt JSON.
_MAX_ENVELOPE_BYTES = 64 * 1024
_MAX_REVISION = 2**53 - 1


def _money(value, *, positive=False):
    if not isinstance(value, str) or not _CASH.fullmatch(value):
        raise ValueError("Cash amount must be a nonnegative decimal string with at most 8 places")
    number = Decimal(value)
    if positive and number <= 0:
        raise ValueError("Risk reservation must be positive")
    return number


def _unique_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate risk-state JSON field")
            result[key] = value
        return result
    def reject_number(_):
        raise ValueError("Non-integer risk-state JSON number")
    return json.loads(raw, object_pairs_hook=unique, parse_float=reject_number,
                      parse_constant=reject_number)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate(state):
    if not isinstance(state, dict) or set(state) != {
        "version", "revision", "kill_switch", "emergency_latched", "limit_cash", "reservations"
    } or type(state["version"]) is not int or state["version"] != 2:
        raise ValueError("Invalid paper risk-state schema")
    if type(state["revision"]) is not int or not 0 <= state["revision"] <= _MAX_REVISION:
        raise ValueError("Invalid paper risk-state revision")
    if type(state["kill_switch"]) is not bool or type(state["emergency_latched"]) is not bool:
        raise ValueError("Invalid paper kill-switch state")
    if state["emergency_latched"] and not state["kill_switch"]:
        raise ValueError("Emergency-latched paper risk state cannot be enabled")
    limit = _money(state["limit_cash"])
    if not state["kill_switch"] and limit <= 0:
        raise ValueError("Enabled paper reservations require a positive cash cap")
    reservations = state["reservations"]
    if not isinstance(reservations, dict) or len(reservations) > _MAX_RESERVATIONS:
        raise ValueError("Invalid paper reservation collection")
    # The first transition must be a policy change: initialize() is killed,
    # so no reservation can occur at revision one. Each retained ID needs
    # another committed revision after that initial policy transition.
    if len(reservations) > max(0, state["revision"] - 1):
        raise ValueError("Paper reservation count exceeds post-policy revision capacity")
    # A retained reservation was created while enabled. A currently killed
    # account must also have a separate subsequent policy-stop or emergency
    # transition; a stop cannot share the final reservation's revision.
    if state["kill_switch"] and reservations and len(reservations) > state["revision"] - 2:
        raise ValueError("Disabled paper reservations require a later stop revision")
    # From the zero-cap initialized state, a positive-cap emergency latch
    # requires both a policy transition and a separate emergency transition.
    # An immediate emergency latch at revision one is valid only at zero cap.
    if state["emergency_latched"] and limit > 0 and state["revision"] < 2:
        raise ValueError("Positive-cap emergency latch requires a prior policy revision")
    # Revision zero is created only by initialize(): no policy, reservation,
    # or emergency transition can legitimately exist before revision one.
    # Reject checksum-recomputed imports that invent a pre-policy cash cap.
    if state["revision"] == 0 and (
        not state["kill_switch"] or state["emergency_latched"]
        or state["limit_cash"] != "0" or reservations
    ):
        raise ValueError("Invalid initial paper risk-state snapshot")
    reserved = Decimal(0)
    for digest, amount in reservations.items():
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid paper reservation identity")
        reserved += _money(amount, positive=True)
    if reserved > limit:
        raise ValueError("Paper risk reservations exceed account cap")
    return reserved


def _account_hash(key):
    if not isinstance(key, str) or not re.fullmatch(r"paper-risk:[0-9a-f]{64}", key):
        raise ValueError("Invalid paper risk account record key")
    return key.split(":", 1)[1]


def _encode(state, *, key):
    account_hash = _account_hash(key)
    _validate(state)
    serialized = _canonical(state)
    envelope = _canonical({"state": state, "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
                           "account_hash": account_hash})
    if len(envelope.encode("utf-8")) > _MAX_ENVELOPE_BYTES:
        raise ValueError("Paper risk-state envelope exceeds size limit")
    return envelope


def _decode(raw, *, key):
    try:
        account_hash = _account_hash(key)
        if (not isinstance(raw, str) or len(raw) > _MAX_ENVELOPE_BYTES
                or len(raw.encode("utf-8")) > _MAX_ENVELOPE_BYTES):
            raise ValueError("Invalid paper risk-state envelope size")
        doc = _unique_json(raw)
        if (not isinstance(doc, dict) or set(doc) != {"state", "sha256", "account_hash"}
                or doc["account_hash"] != account_hash):
            raise ValueError("Risk envelope does not belong to this account")
        reserved = _validate(doc["state"])
        digest = hashlib.sha256(_canonical(doc["state"]).encode()).hexdigest()
        if doc["sha256"] != digest:
            raise ValueError("Risk-state checksum mismatch")
        return doc["state"], reserved
    except (TypeError, ValueError, RecursionError, OverflowError) as exc:
        raise ValueError("Stored paper risk state is corrupt; keep execution disabled") from exc


def _audit_head_matches(db, key, raw, state, reserved):
    """Corroborate a state against the latest same-account audit in this session."""
    account_hash = _account_hash(key)
    # Audit details are emitted by _canonical, with no whitespace.
    # Restrict by exact account-hash JSON field, not raw account ID.
    audit = db.scalar(select(Audit).where(
        Audit.action.in_(("paper.risk.init", "paper.risk.cas")),
        Audit.detail.like('%"account_hash":"' + account_hash + '"%')
    ).order_by(Audit.id.desc()).limit(1))
    if audit is None:
        return False
    try:
        detail = _unique_json(audit.detail)
        if (not isinstance(detail, dict)
                or detail.get("account_hash") != account_hash
                or type(detail.get("revision")) is not int
                or detail["revision"] != state["revision"]
                or detail.get("kill_switch") is not state["kill_switch"]):
            return False
        if state["revision"] == 0:
            return (audit.action == "paper.risk.init"
                    and detail.get("operation") == "initialize")
        operation = detail.get("operation")
        if (audit.action != "paper.risk.cas"
                or operation not in ("policy", "reserve", "emergency_kill")
                or detail.get("state_sha256") != hashlib.sha256(raw.encode()).hexdigest()
                or detail.get("emergency_latched") is not state["emergency_latched"]
                or detail.get("limit_cash") != state["limit_cash"]
                or detail.get("reservation_count") != len(state["reservations"])
                or _money(detail.get("reserved_cash")) != reserved):
            return False
        order_hash = detail.get("reservation_order_hash")
        return (order_hash in state["reservations"] if operation == "reserve"
                else order_hash is None)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return False


class PaperRiskReservationStore:
    """Account-level optimistic CAS; suitable for isolated paper-research testing.

    PostgreSQL READ COMMITTED must be independently race-tested before use in a
    multi-worker service. No broker state or actual losses are inferred here.
    """

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    @staticmethod
    def _key(account_id):
        if not isinstance(account_id, str) or not _ID.fullmatch(account_id):
            raise ValueError("Invalid paper account ID")
        return "paper-risk:" + hashlib.sha256(account_id.encode("ascii")).hexdigest()

    @staticmethod
    def _order_hash(order_id):
        if not isinstance(order_id, str) or not _ID.fullmatch(order_id):
            raise ValueError("Invalid client order ID")
        return hashlib.sha256(order_id.encode("ascii")).hexdigest()

    def _transition(self, key, expected_revision, change, *, operation, order_hash=None):
        if type(expected_revision) is not int or not 0 <= expected_revision < _MAX_REVISION:
            raise ValueError("Invalid expected risk revision")
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                return False
            state, reserved = _decode(raw, key=key)
            if state["revision"] != expected_revision:
                return False
            # The audit and state must agree inside this same transaction
            # before any policy or reservation mutation is attempted.
            if not _audit_head_matches(db, key, raw, state, reserved):
                raise ValueError("Paper risk audit head is missing or inconsistent; halt orders")
            # CAS still protects against a competing state transition.
            if state["revision"] != expected_revision:
                return False
            updated = change(state)
            if updated is None:
                return False
            updated["revision"] = expected_revision + 1
            new_raw = _encode(updated, key=key)
            changed = db.execute(update(Record).where(
                Record.key == key, Record.value == raw).values(value=new_raw))
            if changed.rowcount != 1:
                db.rollback()
                return False
            db.add(Audit(time=int(time.time()), actor="paper-risk-store", action="paper.risk.cas",
                         detail=_canonical({"account_hash": key.split(":", 1)[1],
                                            "operation": operation,
                                            "revision": updated["revision"],
                                            "kill_switch": updated["kill_switch"],
                                            "emergency_latched": updated["emergency_latched"],
                                            "reserved_cash": str(_validate(updated)),
                                            "limit_cash": updated["limit_cash"],
                                            "reservation_count": len(updated["reservations"]),
                                            "reservation_order_hash": order_hash if operation == "reserve" else None,
                                            "state_sha256": hashlib.sha256(new_raw.encode()).hexdigest()})))
            db.commit()
            return True

    def initialize(self, account_id):
        key = self._key(account_id)
        state = {"version": 2, "revision": 0, "kill_switch": True,
                 "emergency_latched": False, "limit_cash": "0", "reservations": {}}
        with self.session_factory() as db:
            try:
                db.execute(insert(Record).values(key=key, value=_encode(state, key=key)))
                db.add(Audit(time=int(time.time()), actor="paper-risk-store", action="paper.risk.init",
                             detail=_canonical({"account_hash": key.split(":", 1)[1],
                                                "operation": "initialize",
                                                "revision": 0, "kill_switch": True})))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False

    def verify_audit_head(self, account_id):
        """Read-only PAPER checkpoint consistency; NOT authenticated audit proof.

        False means the latest retained per-account audit does not corroborate
        the stored state. A concurrent transition may produce a transient false;
        never interpret false, missing, or corrupt evidence as permission.
        """
        key = self._key(account_id)
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                return False
            state, reserved = _decode(raw, key=key)
            return _audit_head_matches(db, key, raw, state, reserved)

    def load(self, account_id):
        key = self._key(account_id)
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
        if raw is None:
            return None  # Absence is NOT permission to trade.
        state, reserved = _decode(raw, key=key)
        return {"revision": state["revision"], "kill_switch": state["kill_switch"],
                "emergency_latched": state["emergency_latched"], "limit_cash": state["limit_cash"],
                "reserved_cash": str(reserved),
                "remaining_risk_capacity_cash": str(_money(state["limit_cash"]) - reserved),
                # A disabled/latching account has no usable reservation capacity.
                # Remaining capacity above is accounting headroom only.
                "reservable_risk_capacity_cash": (
                    "0" if state["kill_switch"] else str(_money(state["limit_cash"]) - reserved)
                ),
                "reservation_count": len(state["reservations"]),
                # A snapshot is never permission to submit even a paper order:
                # quote/position provenance and an atomic journal write are absent.
                "may_execute_paper_order": False,
                "may_execute_real_order": False}

    def set_policy(self, account_id, expected_revision, *, limit_cash, kill_switch,
                   owner_reviewed=False):
        """Owner-reviewed PAPER policy only; bool is NOT authentication."""
        cap = _money(limit_cash)
        if type(kill_switch) is not bool or owner_reviewed is not True:
            raise ValueError("Explicit owner-reviewed paper policy required")
        if not kill_switch and cap <= 0:
            raise ValueError("Positive risk cap required before enabling paper reservations")
        def change(state):
            if state["emergency_latched"]:
                return None  # Emergency latch freezes ALL policy writes, even disabled ones.
            if sum((_money(x) for x in state["reservations"].values()), Decimal(0)) > cap:
                return None
            return {**state, "limit_cash": limit_cash, "kill_switch": kill_switch}
        return self._transition(self._key(account_id), expected_revision, change, operation="policy")

    def reserve(self, account_id, expected_revision, *, client_order_id, risk_cash):
        """Atomically reserve stressed PAPER risk; never places or fills an order."""
        order_hash = self._order_hash(client_order_id)
        amount = _money(risk_cash, positive=True)
        def change(state):
            if state["kill_switch"] or order_hash in state["reservations"]:
                return None
            if len(state["reservations"]) >= _MAX_RESERVATIONS:
                return None  # Never prune IDs silently: no replay after restart.
            existing = sum((_money(x) for x in state["reservations"].values()), Decimal(0))
            if existing + amount > _money(state["limit_cash"]):
                return None
            return {**state, "reservations": {**state["reservations"],
                                               order_hash: risk_cash}}
        return self._transition(self._key(account_id), expected_revision, change,
                                operation="reserve", order_hash=order_hash)

    def engage_kill_switch(self, account_id):
        """Permanently latch emergency stop, retrying competing revisions.

        Never report success without a committed kill state. A service caller
        must stop accepting orders if this returns False or raises.
        """
        key = self._key(account_id)
        for _ in range(20):
            with self.session_factory() as db:
                raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                return False
            state, _ = _decode(raw, key=key)
            if state["kill_switch"] and state["emergency_latched"]:
                if not self.verify_audit_head(account_id):
                    raise ValueError("Paper risk audit head is missing or inconsistent; halt orders")
                return True
            if self._transition(key, state["revision"],
                                lambda current: {**current, "kill_switch": True,
                                                 "emergency_latched": True},
                                operation="emergency_kill"):
                return True
        raise RuntimeError("Could not persist emergency paper kill switch; halt all orders")
