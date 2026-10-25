"""Opt-in, transactional CAS persistence for source-isolated PAPER journal checkpoints.

No API, broker, live order path or automatic database migration is installed.
Uses the existing Record/Audit tables. SQLite is useful for tests; PostgreSQL
READ COMMITTED conditional UPDATE is the intended private-server backend.
"""
import hashlib
import json
import math
import re
import time
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from .db import Record, Audit, Session

MAX_CHECKPOINT_BYTES = 8_000_000
MAX_ACTIONS = 50_000
MAX_REVISION = 2**53 - 1
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_IDENTITY_KEYS = {"instrument", "provider", "venue", "priceSide", "pointValue"}
_CHECKPOINT_KEYS = {"version", "identity", "actions", "orders", "events"}


def _strict_json(raw):
    """Reject duplicate object keys and numeric overflow at every nesting level.

    Standard json.loads accepts duplicate keys and parses 1e999 to float inf,
    even with parse_constant; neither is safe for a replayable trade ledger.
    """
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("Duplicate paper journal JSON field")
            obj[key] = value
        return obj

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("Non-finite paper journal number")
        return number

    def nonfinite(_value):
        raise ValueError("Non-finite paper journal number")

    return json.loads(raw, object_pairs_hook=unique,
                      parse_float=finite_float, parse_constant=nonfinite)


def _identity(value):
    if not isinstance(value, dict) or set(value) != _IDENTITY_KEYS:
        raise ValueError("Invalid paper journal source identity")
    for key in ("instrument", "provider", "venue"):
        item = value[key]
        if not isinstance(item, str) or not 1 <= len(item) <= 160 or not item.strip():
            raise ValueError("Invalid paper journal source identity")
    if value["priceSide"] != "bid-ask":
        raise ValueError("Paper journal requires explicit bid-ask identity")
    point = value["pointValue"]
    if isinstance(point, bool) or not isinstance(point, (int, float)) or not math.isfinite(point) or point <= 0:
        raise ValueError("Invalid paper journal contract point value")
    return value


def _checkpoint(raw, identity):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Paper checkpoint exceeds byte limit")
    try:
        value = _strict_json(raw)
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Invalid paper checkpoint JSON") from exc
    if not isinstance(value, dict) or set(value) != _CHECKPOINT_KEYS or value["version"] != 1:
        raise ValueError("Invalid paper checkpoint schema")
    _identity(value["identity"])
    if value["identity"] != identity:
        raise ValueError("Paper checkpoint source identity mismatch")
    if any(not isinstance(value[k], list) for k in ("actions", "orders", "events")) or len(value["actions"]) > MAX_ACTIONS:
        raise ValueError("Invalid paper checkpoint collections")
    # The TypeScript PaperReplayJournal.restore() must independently replay and
    # validate every action; this store deliberately does not certify paper fills.
    return value


def _revision(value):
    return type(value) is int and 0 <= value <= MAX_REVISION


class PaperJournalStore:
    """Atomic revision CAS. Pass an independent sessionmaker for integration tests.

    A failed transaction never publishes a checkpoint or its audit event.
    Clients must reload on False; they must not assume the submitted order filled.
    """

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    @staticmethod
    def _key(session_id):
        if not isinstance(session_id, str) or not _ID.fullmatch(session_id):
            raise ValueError("Invalid paper journal session ID")
        return "paper-journal:" + hashlib.sha256(session_id.encode("ascii")).hexdigest()

    @staticmethod
    def _decode(value):
        try:
            doc = _strict_json(value)
            if not isinstance(doc, dict) or set(doc) != {"revision", "identity", "json", "sha256"}:
                raise ValueError()
            if not _revision(doc["revision"]):
                raise ValueError()
            _identity(doc["identity"])
            _checkpoint(doc["json"], doc["identity"])
            digest = hashlib.sha256(doc["json"].encode("utf-8")).hexdigest()
            if doc["sha256"] != digest:
                raise ValueError()
            return doc
        except (ValueError, TypeError, RecursionError) as exc:
            raise ValueError("Stored paper journal is corrupt; manual recovery required") from exc

    def load(self, session_id):
        key = self._key(session_id)
        with self.session_factory() as db:
            value = db.scalar(select(Record.value).where(Record.key == key))
            if value is None:
                return None
            doc = self._decode(value)
            return {"revision": doc["revision"], "json": doc["json"], "identity": doc["identity"]}

    def compare_and_swap(self, session_id, identity, expected_revision, next_revision, checkpoint_json):
        key = self._key(session_id)
        _identity(identity)
        if expected_revision is not None and not _revision(expected_revision):
            raise ValueError("Invalid expected paper revision")
        if not _revision(next_revision) or next_revision != (expected_revision + 1 if expected_revision is not None else 0):
            raise ValueError("Paper revision must advance by exactly one")
        _checkpoint(checkpoint_json, identity)
        digest = hashlib.sha256(checkpoint_json.encode("utf-8")).hexdigest()
        next_value = json.dumps({"revision": next_revision, "identity": identity,
                                 "json": checkpoint_json, "sha256": digest},
                                separators=(",", ":"), allow_nan=False)
        with self.session_factory() as db:
            try:
                # An atomic quote+journal session owns its checkpoint path.
                # Standalone CAS must not bypass its source/account binding or
                # advance a journal without advancing the quote replay marker.
                # This read shares the write transaction. A concurrent initial
                # atomic insert is still arbitrated by the journal's unique key;
                # concurrent updates are arbitrated by full-value CAS.
                binding_key = "paper-journal-source:" + key.split(":", 1)[1]
                if db.scalar(select(Record.value).where(Record.key == binding_key)) is not None:
                    return False
                if expected_revision is None:
                    # A unique primary key arbitrates competing first writers.
                    db.execute(insert(Record).values(key=key, value=next_value))
                else:
                    old_value = db.scalar(select(Record.value).where(Record.key == key))
                    if old_value is None:
                        return False
                    old = self._decode(old_value)
                    if old["identity"] != identity:
                        raise ValueError("Stored paper journal source identity mismatch")
                    if old["revision"] != expected_revision:
                        return False
                    # Atomic predicate rechecks the entire previously read value.
                    # In PostgreSQL READ COMMITTED a competing UPDATE must either
                    # win first or cause rowcount=0, never a silent lost update.
                    result = db.execute(update(Record).where(
                        Record.key == key, Record.value == old_value).values(value=next_value))
                    if result.rowcount != 1:
                        db.rollback()
                        return False
                db.add(Audit(time=int(time.time()), actor="owner", action="paper.journal.cas",
                             detail=json.dumps({"session_hash": key.split(":", 1)[1],
                                                "revision": next_revision, "sha256": digest})))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                if expected_revision is None:
                    return False
                raise
