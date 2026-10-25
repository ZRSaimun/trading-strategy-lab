"""Durable, fail-closed PAPER order-intent replay quarantine (disconnected).

No order sender, HTTP route, broker connector, credential, human approval, or
release/reuse operation exists. A review fingerprint is NOT authentication.
Records and audit entries share one database transaction.
"""
import hashlib
import json
import re
import time

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .db import Audit, Record, Session

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{7,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_MS = 8_640_000_000_000_000
_MAX_TTL_MS = 600_000
_MAX_REV = 2**53 - 1
_FIELDS = {"version", "account_hash", "order_hash", "review_sha256",
           "created_ms", "expires_ms", "updated_ms", "revision", "state"}


def _hash_id(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("Invalid account/order alias")
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _key(account_id, client_order_id):
    account_hash = _hash_id(account_id)
    order_hash = _hash_id(client_order_id)
    # Domain-separated account/order pair; neither identifier is persisted.
    digest = hashlib.sha256((account_hash + ":" + order_hash).encode("ascii")).hexdigest()
    return "paper-intent:" + digest, account_hash, order_hash


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _decode(raw, account_hash, order_hash):
    try:
        def unique(pairs):
            out = {}
            for key, value in pairs:
                if key in out:
                    raise ValueError("Duplicate paper intent field")
                out[key] = value
            return out
        doc = json.loads(raw, object_pairs_hook=unique,
                         parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Nonfinite")))
        if not isinstance(doc, dict) or set(doc) != {"state", "sha256"}:
            raise ValueError("Invalid envelope")
        state = doc["state"]
        if not isinstance(state, dict) or set(state) != _FIELDS:
            raise ValueError("Invalid intent schema")
        if (type(state["version"]) is not int or state["version"] != 1
            or state["account_hash"] != account_hash
            or state["order_hash"] != order_hash
            or not isinstance(state["review_sha256"], str)
            or not _SHA.fullmatch(state["review_sha256"])):
            raise ValueError("Invalid intent identity")
        if (any(type(state[field]) is not int for field in
                ("created_ms", "expires_ms", "updated_ms", "revision"))
            or not 0 <= state["created_ms"] < state["expires_ms"] <= _MAX_MS
            or state["expires_ms"] - state["created_ms"] > _MAX_TTL_MS
            or not state["created_ms"] <= state["updated_ms"] <= _MAX_MS
            or not 0 <= state["revision"] <= _MAX_REV):
            raise ValueError("Invalid intent timing/revision")
        if (state["state"] == "PREVIEW_ONLY" and
            (state["revision"] != 0 or state["updated_ms"] != state["created_ms"])):
            raise ValueError("Invalid initial intent")
        if state["state"] == "OUTCOME_UNKNOWN" and state["revision"] != 1:
            raise ValueError("Invalid quarantine revision")
        if state["state"] not in ("PREVIEW_ONLY", "OUTCOME_UNKNOWN"):
            raise ValueError("Unsupported intent state")
        digest = hashlib.sha256(_canonical(state).encode("utf-8")).hexdigest()
        if not isinstance(doc["sha256"], str) or doc["sha256"] != digest:
            raise ValueError("Intent checksum mismatch")
        return state
    except (ValueError, TypeError, OverflowError, RecursionError) as exc:
        raise ValueError("Stored paper order intent corrupt; keep execution disabled") from exc


def _encode(state):
    return _canonical({"state": state,
                       "sha256": hashlib.sha256(_canonical(state).encode()).hexdigest()})


def _public(state):
    return {"state": state["state"], "revision": state["revision"],
            "review_sha256": state["review_sha256"], "expires_ms": state["expires_ms"],
            "requires_reconciliation": state["state"] == "OUTCOME_UNKNOWN",
            "may_execute_paper_order": False, "may_execute_real_order": False,
            "warning": "Registry is not broker-verified, owner authentication or order approval."}


class PaperOrderIntentRegistry:
    """One-use identifiers: duplicate/retry is rejected even after restart.

    PREVIEW_ONLY is not permission to send. OUTCOME_UNKNOWN is permanent until
    a separately designed, authenticated terminal-reconciliation mechanism exists.
    """

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    def load(self, account_id, client_order_id):
        key, account_hash, order_hash = _key(account_id, client_order_id)
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
        return None if raw is None else _public(_decode(raw, account_hash, order_hash))

    def register(self, account_id, client_order_id, *, review_sha256, now_ms, ttl_ms=60_000):
        key, account_hash, order_hash = _key(account_id, client_order_id)
        if not isinstance(review_sha256, str) or not _SHA.fullmatch(review_sha256):
            raise ValueError("Invalid review fingerprint")
        if (type(now_ms) is not int or type(ttl_ms) is not int
            or not 0 <= now_ms < _MAX_MS or not 1 <= ttl_ms <= _MAX_TTL_MS
            or now_ms + ttl_ms > _MAX_MS):
            raise ValueError("Invalid server time or review TTL")
        state = {"version": 1, "account_hash": account_hash, "order_hash": order_hash,
                 "review_sha256": review_sha256, "created_ms": now_ms,
                 "expires_ms": now_ms + ttl_ms, "updated_ms": now_ms,
                 "revision": 0, "state": "PREVIEW_ONLY"}
        with self.session_factory() as db:
            try:
                db.execute(insert(Record).values(key=key, value=_encode(state)))
                db.add(Audit(time=int(time.time()), actor="paper-intent-registry",
                             action="paper.intent.register",
                             detail=_canonical({"intent_key_hash": key.split(":", 1)[1],
                                                "review_sha256": review_sha256,
                                                "revision": 0, "state": "PREVIEW_ONLY"})))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                # A duplicate ID never authorizes an order or overwrites a prior intent.
                return False

    def mark_outcome_unknown(self, account_id, client_order_id, *, review_sha256,
                             expected_revision, now_ms):
        key, account_hash, order_hash = _key(account_id, client_order_id)
        if (not isinstance(review_sha256, str) or not _SHA.fullmatch(review_sha256)
            or type(expected_revision) is not int or expected_revision != 0
            or type(now_ms) is not int or not 0 <= now_ms <= _MAX_MS):
            raise ValueError("Invalid quarantine request")
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                return False
            state = _decode(raw, account_hash, order_hash)
            if (state["state"] != "PREVIEW_ONLY" or state["revision"] != expected_revision
                or state["review_sha256"] != review_sha256 or now_ms < state["updated_ms"]):
                return False
            next_state = {**state, "state": "OUTCOME_UNKNOWN", "revision": 1,
                          "updated_ms": now_ms}
            result = db.execute(update(Record).where(Record.key == key, Record.value == raw)
                                .values(value=_encode(next_state)))
            if result.rowcount != 1:
                db.rollback()
                return False
            db.add(Audit(time=int(time.time()), actor="paper-intent-registry",
                         action="paper.intent.quarantine",
                         detail=_canonical({"intent_key_hash": key.split(":", 1)[1],
                                            "review_sha256": review_sha256,
                                            "revision": 1, "state": "OUTCOME_UNKNOWN"})))
            db.commit()
            return True
