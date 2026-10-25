"""Isolated, fail-closed PAPER daily-loss latch. No broker or order path.

Observations are caller-declared, NOT authenticated brokerage receipts. The latch
is monotonic within one UTC trading day and persists through process restarts.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
import re
import time

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from .db import Audit, Record, Session

_MAX_MS = 8_640_000_000_000_000
_MAX_SEQ = 2**53 - 1
_ID = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_FIELDS = {"version", "day", "currency", "cap", "revision", "sequence",
           "observed_ms", "realized", "unrealized", "reserved", "peak_loss", "latched"}


def _money(value, *, positive=False, nonnegative=False):
    if not isinstance(value, str) or not re.fullmatch(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]{1,8})?", value):
        raise ValueError("Money must be a finite decimal string with at most 8 places")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid money") from exc
    if not number.is_finite() or abs(number) > Decimal("1000000000000000"):
        raise ValueError("Money exceeds supported bounds")
    if positive and number <= 0 or nonnegative and number < 0:
        raise ValueError("Invalid sign for money")
    return number


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("Expected ISO UTC trading day")
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except ValueError as exc:
        raise ValueError("Invalid UTC trading day") from exc
    return value


def _decode(raw, *, expected_day=None):
    try:
        def unique(pairs):
            out = {}
            for k, v in pairs:
                if k in out:
                    raise ValueError("duplicate field")
                out[k] = v
            return out
        data = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(data, dict) or set(data) != _FIELDS or data["version"] != 1:
            raise ValueError()
        _day(data["day"])
        if expected_day is not None and data["day"] != expected_day:
            raise ValueError("Policy day does not match record key")
        if not isinstance(data["currency"], str) or not _CURRENCY.fullmatch(data["currency"]):
            raise ValueError()
        for key in ("cap", "peak_loss", "reserved"):
            _money(data[key], positive=key == "cap", nonnegative=key != "cap")
        for key in ("realized", "unrealized"):
            _money(data[key])
        if (type(data["revision"]) is not int or data["revision"] < 0 or data["revision"] > _MAX_SEQ
            or type(data["sequence"]) is not int or data["sequence"] < 0 or data["sequence"] > _MAX_SEQ
            or type(data["observed_ms"]) is not int or not 0 <= data["observed_ms"] <= _MAX_MS
            or type(data["latched"]) is not bool):
            raise ValueError()
        current_loss = max(Decimal(0), -(_money(data["realized"]) + min(_money(data["unrealized"]), Decimal(0)) - _money(data["reserved"])))
        if _money(data["peak_loss"]) < current_loss or data["latched"] != (_money(data["peak_loss"]) >= _money(data["cap"])):
            raise ValueError()
        # A valid record is either a pristine initialization or an observed
        # revision. Reject forged resets and timestamp/sequence discontinuities
        # rather than allowing a corrupt record to appear unlatched.
        if data["revision"] == 0:
            if (data["sequence"] != 0 or data["observed_ms"] != 0
                or any(_money(data[k]) != 0 for k in
                       ("realized", "unrealized", "reserved", "peak_loss"))):
                raise ValueError("Invalid initial state")
        else:
            if data["sequence"] < data["revision"] or data["observed_ms"] == 0:
                raise ValueError("Invalid observed state")
            try:
                observed_day = datetime.fromtimestamp(
                    data["observed_ms"] / 1000, tz=timezone.utc
                ).date().isoformat()
            except (ValueError, OverflowError, OSError) as exc:
                raise ValueError("Invalid stored observation timestamp") from exc
            if observed_day != data["day"]:
                raise ValueError("Stored observation belongs to a different UTC day")
        return data
    except (ValueError, TypeError, RecursionError, OverflowError) as exc:
        raise ValueError("Corrupt paper daily-loss state; manual recovery required") from exc


def _encode(doc):
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), allow_nan=False)


class PaperDailyLossBreaker:
    """Persistence-only paper risk monitor; never grants execution permission."""

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    @staticmethod
    def _key(account_id, day):
        if not isinstance(account_id, str) or not _ID.fullmatch(account_id):
            raise ValueError("Invalid paper account alias")
        _day(day)
        digest = hashlib.sha256((account_id + "\0" + day).encode("ascii")).hexdigest()
        return "paper-daily-loss:" + digest

    @staticmethod
    def _public(doc):
        return {**doc, "source_authenticated": False, "may_execute_paper_order": False,
                "may_execute_real_order": False,
                "warning": "Caller-declared P&L is not broker-reconciled; this latch is not an execution gate."}

    def load(self, account_id, day):
        key = self._key(account_id, day)
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            return None if raw is None else self._public(_decode(raw, expected_day=day))

    def initialize(self, account_id, day, currency, cap):
        key = self._key(account_id, day)
        if not isinstance(currency, str) or not _CURRENCY.fullmatch(currency):
            raise ValueError("Invalid account currency")
        cap = _money(cap, positive=True)
        doc = dict(version=1, day=day, currency=currency, cap=str(cap), revision=0,
                   sequence=0, observed_ms=0, realized="0", unrealized="0", reserved="0",
                   peak_loss="0", latched=False)
        with self.session_factory() as db:
            try:
                db.execute(insert(Record).values(key=key, value=_encode(doc)))
                db.add(Audit(time=int(time.time()), actor="system", action="paper.loss.initialize",
                             detail=_encode({"account_day_hash": key.split(":", 1)[1], "cap": str(cap),
                                             "currency": currency})))
                db.commit()
                return True
            except IntegrityError:
                db.rollback()
                return False

    def observe(self, account_id, day, *, sequence, observed_ms, now_ms,
                realized, unrealized, reserved, max_age_ms=10_000):
        key = self._key(account_id, day)
        if (type(sequence) is not int or not 1 <= sequence <= _MAX_SEQ
            or type(observed_ms) is not int or type(now_ms) is not int
            or not 0 <= observed_ms <= now_ms <= _MAX_MS
            or type(max_age_ms) is not int or not 100 <= max_age_ms <= 60_000
            or now_ms - observed_ms > max_age_ms):
            raise ValueError("Stale, future or invalid paper observation")
        try:
            observation_day = datetime.fromtimestamp(observed_ms / 1000, tz=timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("Invalid UTC observation time") from exc
        if observation_day != day:
            raise ValueError("Observation UTC day does not match policy day")
        realized_d = _money(realized)
        unrealized_d = _money(unrealized)
        reserved_d = _money(reserved, nonnegative=True)
        loss = max(Decimal(0), -(realized_d + min(unrealized_d, Decimal(0)) - reserved_d))
        if loss > Decimal("1000000000000000"):
            raise ValueError("Aggregate paper loss exceeds supported bounds")
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                raise ValueError("Paper loss policy not initialized")
            old = _decode(raw, expected_day=day)
            if sequence <= old["sequence"] or observed_ms <= old["observed_ms"]:
                raise ValueError("Replay or out-of-order paper loss observation")
            if old["revision"] == _MAX_SEQ:
                raise ValueError("Paper loss revision exhausted")
            peak = max(_money(old["peak_loss"]), loss)
            doc = {**old, "revision": old["revision"] + 1, "sequence": sequence,
                   "observed_ms": observed_ms, "realized": str(realized_d),
                   "unrealized": str(unrealized_d), "reserved": str(reserved_d),
                   "peak_loss": str(peak), "latched": peak >= _money(old["cap"])}
            result = db.execute(update(Record).where(Record.key == key, Record.value == raw)
                                .values(value=_encode(doc)))
            if result.rowcount != 1:
                db.rollback()
                return False  # CAS conflict: caller must reload; never assume clear
            db.add(Audit(time=int(time.time()), actor="system", action="paper.loss.observe",
                         detail=_encode({"account_day_hash": key.split(":", 1)[1],
                                         "revision": doc["revision"], "sequence": sequence,
                                         "peak_loss": str(peak), "latched": doc["latched"]})))
            db.commit()
            return self._public(doc)
