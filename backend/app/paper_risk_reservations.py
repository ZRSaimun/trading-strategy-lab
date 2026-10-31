"""Opt-in, fail-closed, persistent PAPER-only risk reservations.

Not wired to an HTTP route, order sender, broker, or the paper fill journal.
A caller must authenticate the owner and reconcile terminal positions separately.
All account/order identifiers are hashed before persistence or audit logging.
"""
import hashlib
import json
import re
import time
from decimal import Decimal, InvalidOperation

from sqlalchemy import LargeBinary, case, cast, func, insert, or_, select, update
from sqlalchemy.exc import IntegrityError

from .db import Audit, Record, Session

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_CASH = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_MAX_RESERVATIONS = 500
# Hard bound on persisted envelopes before parsing untrusted/corrupt JSON.
_MAX_ENVELOPE_BYTES = 64 * 1024
# Bound self-attested audit JSON before parsing; this does not authenticate it.
_MAX_AUDIT_DETAIL_BYTES = 4 * 1024
# Bound historical verification work; oversized histories require manual review.
_MAX_AUDIT_HISTORY_ROWS = 4096
_MAX_REVISION = 2**53 - 1


def _money(value, *, positive=False):
    if not isinstance(value, str) or not _CASH.fullmatch(value):
        raise ValueError("Cash amount must be a nonnegative decimal string with at most 8 places")
    number = Decimal(value)
    if positive and number <= 0:
        raise ValueError("Risk reservation must be positive")
    return number


def _audit_cash(value):
    """Parse the canonical Decimal audit representation, including 1E-8."""
    if not isinstance(value, str) or len(value) > 48:
        raise ValueError("Invalid paper audit cash amount")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid paper audit cash amount") from exc
    if (not amount.is_finite() or amount < 0
            or amount.as_tuple().exponent < -8 or str(amount) != value):
        raise ValueError("Invalid paper audit cash amount")
    return amount


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


def _audit_json(raw):
    """Reject oversized audit receipts before allocating parsed JSON objects."""
    if (not isinstance(raw, str) or len(raw) > _MAX_AUDIT_DETAIL_BYTES
            or len(raw.encode("utf-8")) > _MAX_AUDIT_DETAIL_BYTES):
        raise ValueError("Paper risk audit detail exceeds size limit")
    # Every receipt written by this store uses _canonical(). Accepting a
    # semantically equivalent but byte-different receipt would conceal a
    # textual audit mutation (whitespace, escapes, key order or numeric form).
    # This is an integrity preflight, NOT a signature or authenticated ledger.
    detail = _unique_json(raw)
    if raw != _canonical(detail):
        raise ValueError("Noncanonical paper risk audit detail")
    return detail


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
        # _encode always emits canonical bytes. A valid inner checksum alone
        # must not authorize a byte-rewritten persisted account envelope,
        # including revision-zero snapshots with no state digest in audit.
        if raw != _canonical(doc):
            raise ValueError("Noncanonical paper risk-state envelope")
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



def _sql_utf8_byte_length(db, column):
    """Count actual stored UTF-8 bytes, including embedded NUL characters.

    SQLite length(TEXT) stops at the first NUL and counts Unicode characters;
    length(CAST(TEXT AS BLOB)) counts all bytes. PostgreSQL octet_length(TEXT)
    counts UTF-8 bytes. Fail closed on untested SQL dialects.
    """
    dialect = db.get_bind().dialect.name
    if dialect == "sqlite":
        return func.length(cast(column, LargeBinary))
    if dialect == "postgresql":
        return func.octet_length(column)
    raise ValueError("Unsupported PAPER risk storage dialect")


def _read_bounded_state(db, key):
    """SQL-side byte preflight: never materialize an oversized risk envelope.

    A single statement returns either the byte-bounded text or NULL. The
    independent Python _decode check remains a defense in depth. Missing rows
    remain distinct from corrupt oversized rows.
    """
    length = _sql_utf8_byte_length(db, Record.value)
    row = db.execute(select(
        length,
        case((length > _MAX_ENVELOPE_BYTES, None), else_=Record.value),
    ).where(Record.key == key)).one_or_none()
    if row is None:
        return None
    char_count, raw = row
    if char_count is None or char_count > _MAX_ENVELOPE_BYTES or raw is None:
        raise ValueError("Stored paper risk state is corrupt; keep execution disabled")
    return raw


def _account_audit_match(key):
    """Locate retained account receipts using the store's canonical hash field.

    This is a self-attested text locator, not an authenticated ownership index.
    """
    return Audit.detail.like('%"account_hash":"' + _account_hash(key) + '"%')


def _audit_head_matches(db, key, raw, state, reserved):
    """Corroborate a state against the latest same-account audit in this session."""
    account_hash = _account_hash(key)
    # Audit details are emitted by _canonical, with no whitespace.
    # Restrict by exact account-hash JSON field, not raw account ID.
    # Count every receipt carrying this account hash, including unknown
    # actions. Filtering to known actions silently hides unauthorized writes.
    # The exact JSON-field locator is self-attested, not authenticated.
    account_match = _account_audit_match(key)
    # Reject invalid receipt metadata in SQL before materializing ORM rows.
    # The writer records positive integral epoch seconds. SQLite can store
    # text in an INTEGER column, so compare its actual storage type as well.
    # Do not assert timestamp freshness/order: there is no trusted clock.
    invalid_time = or_(Audit.time.is_(None), Audit.time <= 0)
    if db.get_bind().dialect.name == "sqlite":
        invalid_time = or_(invalid_time, func.typeof(Audit.time) != "integer")
    if db.scalar(select(Audit.id).where(
        account_match,
        or_(Audit.actor.is_(None),
            Audit.actor != "paper-risk-store",
            Audit.action.is_(None),
            Audit.action.not_in(("paper.risk.init", "paper.risk.cas")),
            invalid_time),
    ).limit(1)) is not None:
        return False
    # Never accept an unbounded scan as evidence of a verified audit history.
    # Revision 0 has one init receipt; each CAS adds exactly one more.
    if state["revision"] >= _MAX_AUDIT_HISTORY_ROWS:
        return False
    # Check actual stored UTF-8 bytes in SQL before fetching receipt text.
    # SQLite TEXT length would miss trailing bytes after an embedded NUL.
    # _audit_json still independently enforces the byte and canonical bounds.
    if db.scalar(select(Audit.id).where(
        account_match, _sql_utf8_byte_length(db, Audit.detail) > _MAX_AUDIT_DETAIL_BYTES
    ).limit(1)) is not None:
        return False
    audits = db.scalars(select(Audit).where(
        account_match
    ).order_by(Audit.id.desc()).limit(2)).all()
    # The latest checkpoint alone cannot reveal a deleted immediately prior
    # transition or a duplicated/replayed head. Check the adjacent revision
    # without pretending to authenticate the entire audit history.
    if not audits or audits[0].actor != "paper-risk-store":
        return False
    audit = audits[0]
    try:
        # A receipt COUNT alone can be preserved by deleting an old event and
        # inserting a duplicate. Walk the bounded account-specific history in
        # append order and require exact consecutive revisions, actor and
        # operation schema. The latest two still receive stronger state checks.
        history = db.execute(select(Audit.action, Audit.actor, Audit.detail).where(
            account_match
        ).order_by(Audit.id.asc()).limit(_MAX_AUDIT_HISTORY_ROWS + 1)).all()
        if len(history) != state["revision"] + 1:
            return False
        previous_entry = None
        historical_orders = set()
        historical_reservations = {}
        historical_reserved = Decimal(0)
        for expected, (history_action, history_actor, history_detail) in enumerate(history):
            entry = _audit_json(history_detail)
            if (history_actor != "paper-risk-store"
                    or not isinstance(entry, dict)
                    or entry.get("account_hash") != account_hash
                    or type(entry.get("revision")) is not int
                    or entry["revision"] != expected):
                return False
            if expected == 0:
                if (history_action != "paper.risk.init"
                        or entry != {
                            "account_hash": account_hash,
                            "operation": "initialize",
                            "revision": 0,
                            "kill_switch": True,
                        }):
                    return False
            elif (history_action != "paper.risk.cas"
                    or set(entry) != {
                        "account_hash", "operation", "revision", "kill_switch",
                        "emergency_latched", "reserved_cash", "limit_cash",
                        "reservation_count", "reservation_order_hash", "state_sha256"
                    }
                    or entry.get("operation") not in ("policy", "reserve", "emergency_kill")):
                return False
            else:
                # Older receipts must still describe a *possible* PAPER
                # checkpoint. A contiguous revision number and field names
                # alone would allow malformed cash, bools or order digests to
                # pass the historical audit census.
                op = entry["operation"]
                count = entry["reservation_count"]
                stopped = entry["kill_switch"]
                latched = entry["emergency_latched"]
                order = entry["reservation_order_hash"]
                checksum = entry["state_sha256"]
                cash = _audit_cash(entry["reserved_cash"])
                cap = _money(entry["limit_cash"])
                if (type(count) is not int or not 0 <= count <= _MAX_RESERVATIONS
                        or type(stopped) is not bool or type(latched) is not bool
                        or not isinstance(checksum, str)
                        or not re.fullmatch(r"[0-9a-f]{64}", checksum)
                        or cash > cap or (count == 0) != (cash == 0)
                        or (not stopped and cap <= 0)
                        or (latched and not stopped)
                        or (op == "reserve" and (
                            stopped or latched or count == 0
                            or not isinstance(order, str)
                            or not re.fullmatch(r"[0-9a-f]{64}", order)))
                        or (op != "reserve" and order is not None)
                        or (op == "emergency_kill" and not latched)
                        or (op != "emergency_kill" and latched)):
                    return False
                # The full retained receipt sequence must describe possible
                # transitions, not just individually plausible snapshots.
                # No reservation is ever released by this prototype.
                if expected == 1:
                    # Initialization starts killed, with no cash or orders.
                    if (op == "reserve" or count != 0 or cash != 0
                            or (op == "emergency_kill" and cap != 0)):
                        return False
                else:
                    prior_count = previous_entry["reservation_count"]
                    prior_cash = _audit_cash(previous_entry["reserved_cash"])
                    prior_cap = _money(previous_entry["limit_cash"])
                    if previous_entry["emergency_latched"]:
                        return False  # No writes after an emergency latch.
                    if op == "reserve":
                        if (previous_entry["kill_switch"]
                                or count != prior_count + 1 or cap != prior_cap):
                            return False
                    elif (count != prior_count or cash != prior_cash
                          or (op == "emergency_kill" and cap != prior_cap)):
                        return False
                if op == "reserve":
                    if order in historical_orders or order not in state["reservations"]:
                        return False
                    historical_orders.add(order)
                    if (expected > 1 and cash != prior_cash + _money(
                            state["reservations"][order], positive=True)):
                        return False
                    historical_reservations[order] = state["reservations"][order]
                    historical_reserved += _money(state["reservations"][order], positive=True)
                # Verify every older receipt against its reconstructed prefix,
                # not only the latest two adjacent audit checkpoints.
                # Compare the exact Decimal serialization emitted by the
                # writer, not only numeric equality. A rewritten old receipt
                # with "0.00" instead of "0" or "1.0" instead of "1" is
                # inconsistent even when its numeric value is unchanged.
                if entry["reserved_cash"] != str(historical_reserved):
                    return False
                historical_state = {
                    "version": 2,
                    "revision": expected,
                    "kill_switch": stopped,
                    "emergency_latched": latched,
                    "limit_cash": entry["limit_cash"],
                    "reservations": dict(historical_reservations),
                }
                historical_envelope = _encode(historical_state, key=key)
                if checksum != hashlib.sha256(historical_envelope.encode()).hexdigest():
                    return False
            previous_entry = entry
        if historical_orders != set(state["reservations"]):
            return False
        if state["revision"] == 0:
            if len(audits) != 1:
                return False
        else:
            if len(audits) != 2:
                return False
            predecessor = audits[1]
            previous = _audit_json(predecessor.detail)
            expected_action = ("paper.risk.init" if state["revision"] == 1
                               else "paper.risk.cas")
            if (predecessor.actor != "paper-risk-store"
                    or predecessor.action != expected_action
                    or not isinstance(previous, dict)
                    or previous.get("account_hash") != account_hash
                    or type(previous.get("revision")) is not int
                    or previous["revision"] != state["revision"] - 1):
                return False
            if state["revision"] == 1:
                if (set(previous) != {"account_hash", "operation", "revision", "kill_switch"}
                        or previous.get("operation") != "initialize"
                        or previous.get("kill_switch") is not True):
                    return False
            elif (set(previous) != {
                "account_hash", "operation", "revision", "kill_switch",
                "emergency_latched", "reserved_cash", "limit_cash",
                "reservation_count", "reservation_order_hash", "state_sha256"
            } or previous.get("operation") not in ("policy", "reserve", "emergency_kill")):
                return False
            if state["revision"] > 1:
                # The adjacent checkpoint must describe a reachable previous
                # state, not merely have a matching revision and field names.
                previous_count = previous.get("reservation_count")
                if (type(previous_count) is not int
                        or not 0 <= previous_count <= _MAX_RESERVATIONS
                        or type(previous.get("kill_switch")) is not bool
                        or type(previous.get("emergency_latched")) is not bool
                        or previous["emergency_latched"]
                        or previous["operation"] == "emergency_kill"
                        or (previous["operation"] == "reserve"
                            and (previous["kill_switch"] or previous_count == 0))):
                    return False
                # The preceding receipt must be financially possible, even
                # when its own state envelope is no longer the current one.
                previous_cash = _audit_cash(previous.get("reserved_cash"))
                previous_limit = _money(previous.get("limit_cash"))
                previous_order = previous.get("reservation_order_hash")
                if (previous_cash > previous_limit
                        or (previous_count == 0) != (previous_cash == 0)
                        or (not previous["kill_switch"] and previous_limit <= 0)
                        or (previous["operation"] == "reserve"
                            and (not isinstance(previous_order, str)
                                 or not re.fullmatch(r"[0-9a-f]{64}", previous_order)
                                 or previous_order not in state["reservations"]))
                        or (previous["operation"] != "reserve" and previous_order is not None)):
                    return False
        detail = _audit_json(audit.detail)
        if (not isinstance(detail, dict)
                or detail.get("account_hash") != account_hash
                or type(detail.get("revision")) is not int
                or detail["revision"] != state["revision"]
                or detail.get("kill_switch") is not state["kill_switch"]):
            return False
        if state["revision"] == 0:
            return (audit.action == "paper.risk.init"
                    and set(detail) == {"account_hash", "operation", "revision", "kill_switch"}
                    and detail.get("operation") == "initialize")
        operation = detail.get("operation")
        if (audit.action != "paper.risk.cas"
                or set(detail) != {
                    "account_hash", "operation", "revision", "kill_switch",
                    "emergency_latched", "reserved_cash", "limit_cash",
                    "reservation_count", "reservation_order_hash", "state_sha256"
                }
                or operation not in ("policy", "reserve", "emergency_kill")
                or detail.get("state_sha256") != hashlib.sha256(raw.encode()).hexdigest()
                or detail.get("emergency_latched") is not state["emergency_latched"]
                or detail.get("limit_cash") != state["limit_cash"]
                or detail.get("reservation_count") != len(state["reservations"])
                or detail.get("reserved_cash") != str(reserved)):
            return False
        if state["revision"] > 1:
            # A reserve adds exactly one retained ID; policy and emergency
            # transitions never add or release IDs. A reserve also cannot
            # follow a disabled checkpoint without an intervening policy CAS.
            expected_previous_count = len(state["reservations"]) - int(operation == "reserve")
            if previous["reservation_count"] != expected_previous_count:
                return False
            # Reservation increases committed cash risk; policy/emergency
            # cannot silently release it. Only an owner-reviewed policy may
            # change the cap, never a reserve or emergency-stop transition.
            if operation == "reserve":
                if (previous["kill_switch"]
                        or previous["limit_cash"] != state["limit_cash"]
                        or previous_cash >= reserved
                        or (previous["operation"] == "reserve"
                            and previous_order == detail.get("reservation_order_hash"))):
                    return False
                # The last reservation's exact retained cash amount must
                # explain the entire increase from the adjacent checkpoint.
                # A merely smaller preceding total is not sufficient proof.
                latest_order = detail.get("reservation_order_hash")
                if (not isinstance(latest_order, str)
                        or latest_order not in state["reservations"]
                        or previous_cash + _money(
                            state["reservations"][latest_order], positive=True
                        ) != reserved):
                    return False
            else:
                if previous_cash != reserved:
                    return False
                if (operation == "emergency_kill"
                        and previous["limit_cash"] != state["limit_cash"]):
                    return False
            # Every CAS receipt records the digest of its full persisted
            # envelope. Reconstruct the immediately preceding state using
            # the retained IDs and the prior policy fields, then verify that
            # receipt. This catches inconsistent adjacent history but is not
            # authentication: a database writer can recompute both hashes.
            prior_reservations = dict(state["reservations"])
            if operation == "reserve":
                prior_reservations.pop(detail["reservation_order_hash"])
            prior_state = {
                **state,
                "revision": state["revision"] - 1,
                "kill_switch": previous["kill_switch"],
                "emergency_latched": previous["emergency_latched"],
                "limit_cash": previous["limit_cash"],
                "reservations": prior_reservations,
            }
            prior_envelope = _encode(prior_state, key=key)
            if previous.get("state_sha256") != hashlib.sha256(
                prior_envelope.encode()
            ).hexdigest():
                return False
        order_hash = detail.get("reservation_order_hash")
        # The audit operation must be possible for the state it claims to
        # checkpoint. Matching fields/checksum alone cannot turn a policy
        # transition into an emergency stop or a stopped state into a reserve.
        if operation == "reserve":
            return (not state["kill_switch"] and not state["emergency_latched"]
                    and order_hash in state["reservations"])
        if order_hash is not None:
            return False
        if operation == "emergency_kill":
            return state["kill_switch"] and state["emergency_latched"]
        return not state["emergency_latched"]  # A policy CAS cannot latch an emergency.

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
            raw = _read_bounded_state(db, key)
            if raw is None:
                return False
            state, reserved = _decode(raw, key=key)
            if state["revision"] != expected_revision:
                return False
            # The verifier can inspect at most _MAX_AUDIT_HISTORY_ROWS receipts.
            # Keep the last verifiable revision available for a persistent
            # emergency latch: ordinary policy/reservation writes must leave
            # one spare CAS slot. Otherwise a valid write could strand the
            # account with an unverifiable history and no durable stop slot.
            if operation == "emergency_kill":
                if expected_revision >= _MAX_AUDIT_HISTORY_ROWS - 1:
                    return False
            elif expected_revision >= _MAX_AUDIT_HISTORY_ROWS - 2:
                return False
            # The audit and state must agree inside this same transaction
            # before any policy or reservation mutation is attempted.
            if not _audit_head_matches(db, key, raw, state, reserved):
                raise ValueError("Paper risk audit head is missing or inconsistent; halt orders")
            # The conditional SQL UPDATE below still protects against races.
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
            # A missing state row is not proof that this is a fresh account.
            # If retained receipts survive a lost/deleted state, refuse to
            # mint a new revision-zero snapshot over that existing history.
            # This check shares the audit verifier's conservative locator.
            if db.scalar(select(Audit.id).where(
                _account_audit_match(key)
            ).limit(1)) is not None:
                return False
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
            raw = _read_bounded_state(db, key)
            if raw is None:
                return False
            state, reserved = _decode(raw, key=key)
            return _audit_head_matches(db, key, raw, state, reserved)

    def load(self, account_id):
        key = self._key(account_id)
        with self.session_factory() as db:
            raw = _read_bounded_state(db, key)
            if raw is None:
                return None  # Absence is NOT permission to trade.
            state, reserved = _decode(raw, key=key)
            # Keep the snapshot and its audit-head check in one DB session.
            # This is a conservative diagnostic, not authenticated evidence.
            audit_verified = _audit_head_matches(db, key, raw, state, reserved)
        return {"revision": state["revision"], "kill_switch": state["kill_switch"],
                "audit_head_verified": audit_verified,
                "emergency_latched": state["emergency_latched"], "limit_cash": state["limit_cash"],
                "reserved_cash": str(reserved),
                "remaining_risk_capacity_cash": str(_money(state["limit_cash"]) - reserved),
                # Accounting headroom is not usable when the audit checkpoint
                # is absent or inconsistent, even if the persisted switch is off.
                "reservable_risk_capacity_cash": (
                    "0" if (state["kill_switch"] or not audit_verified
                            or state["revision"] >= _MAX_AUDIT_HISTORY_ROWS - 2)
                    else str(_money(state["limit_cash"]) - reserved)
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
                raw = _read_bounded_state(db, key)
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
