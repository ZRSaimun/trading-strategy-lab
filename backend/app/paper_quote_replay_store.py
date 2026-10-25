"""Disconnected, fail-closed quote replay marker for paper/broker reconciliation.

No broker authentication, HTTP route, order placement, database migration or live
execution. The caller MUST supply a trusted server clock and authenticated
source upstream; this store does not verify either claim.
"""
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re
import time
from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError
from .db import Audit, Record, Session

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{7,95}\Z")
_SOURCE_KEYS = {"account_alias", "provider", "venue", "instrument"}
_QUOTE_KEYS = {"quote_id", "sequence", "observed_at_ms", "received_at_ms", "bid", "ask"}
_DOC_KEYS = {"version", "identity_sha256", "revision", "sequence", "observed_at_ms",
             "received_at_ms", "accepted_at_ms", "quote_sha256", "recent_quote_hashes", "checksum"}
_MAX_MS = 8_640_000_000_000_000
_MAX_SEQ = 2**53 - 1


def _canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _digest(obj):
    return hashlib.sha256(_canonical(obj).encode("ascii")).hexdigest()


def _source(source):
    if not isinstance(source, dict) or set(source) != _SOURCE_KEYS:
        raise ValueError("Invalid quote source identity")
    for value in source.values():
        if not isinstance(value, str) or not 1 <= len(value) <= 80 or not value.strip():
            raise ValueError("Invalid quote source identity")
    return _digest(source)


def _integer(value, ceiling):
    return type(value) is int and 0 <= value <= ceiling


def _money(value, *, maximum):
    if not isinstance(value, str) or not 1 <= len(value) <= 48:
        raise ValueError("Quote prices and limits must be bounded decimal strings")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal") from exc
    if not number.is_finite() or not 0 < number <= maximum or len(number.as_tuple().digits) > 28 or not -12 <= number.as_tuple().exponent <= 12:
        raise ValueError("Invalid bounded decimal")
    return number


def _quote(quote):
    if not isinstance(quote, dict) or set(quote) != _QUOTE_KEYS:
        raise ValueError("Invalid quote schema")
    if not isinstance(quote["quote_id"], str) or not _ID.fullmatch(quote["quote_id"]):
        raise ValueError("Invalid quote identifier")
    if not _integer(quote["sequence"], _MAX_SEQ):
        raise ValueError("Invalid quote sequence")
    if not all(_integer(quote[k], _MAX_MS) for k in ("observed_at_ms", "received_at_ms")):
        raise ValueError("Invalid quote timestamps")
    bid = _money(quote["bid"], maximum=Decimal("1000000000000"))
    ask = _money(quote["ask"], maximum=Decimal("1000000000000"))
    return bid, ask


def _decode(raw, identity_sha):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("Duplicate stored quote field")
            value[key] = item
        return value
    try:
        if not isinstance(raw, str) or len(raw) > 8000:
            raise ValueError("Oversized quote marker")
        doc = json.loads(raw, object_pairs_hook=unique)
        if not isinstance(doc, dict) or set(doc) != _DOC_KEYS or doc["version"] != 1:
            raise ValueError("Invalid quote marker schema")
        if doc["identity_sha256"] != identity_sha:
            raise ValueError("Quote marker source mismatch")
        if not all(_integer(doc[k], _MAX_SEQ if k in ("revision", "sequence") else _MAX_MS)
                   for k in ("revision", "sequence", "observed_at_ms", "received_at_ms", "accepted_at_ms")):
            raise ValueError("Invalid quote marker counters")
        if not isinstance(doc["quote_sha256"], str) or not re.fullmatch(r"[0-9a-f]{64}", doc["quote_sha256"]):
            raise ValueError("Invalid quote marker digest")
        recent = doc["recent_quote_hashes"]
        if (not isinstance(recent, list) or not 1 <= len(recent) <= 64
                or any(not isinstance(h, str) or not re.fullmatch(r"[0-9a-f]{64}", h) for h in recent)
                or len(set(recent)) != len(recent) or recent[-1] != doc["quote_sha256"]):
            raise ValueError("Invalid quote marker replay history")
        checksum = doc.pop("checksum")
        if not isinstance(checksum, str) or checksum != _digest(doc):
            raise ValueError("Quote marker checksum mismatch")
        doc["checksum"] = checksum
        return doc
    except (ValueError, TypeError, RecursionError) as exc:
        raise ValueError("Stored quote replay marker corrupt; manual reconciliation required") from exc


def _result(reason, accepted=False, revision=None):
    return {"status": "ACCEPTED_UNVERIFIED" if accepted else "HOLD_RECONCILIATION",
            "reason": reason, "revision": revision,
            "quote_authenticated": False, "paper_order_permitted": False,
            "live_order_permitted": False}


class PaperQuoteReplayStore:
    """Persist only accepted quote sequence markers, not source prices or secrets.

    Concurrent writers arbitrate with unique insert or full-value CAS. Rejections
    never move the last accepted marker; a caller must reconcile before retrying.
    """

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    @staticmethod
    def _key(source):
        return "paper-quote:" + _source(source)

    def load_marker(self, source):
        key = self._key(source)
        with self.session_factory() as db:
            raw = db.scalar(select(Record.value).where(Record.key == key))
            if raw is None:
                return None
            return _decode(raw, key.split(":", 1)[1]).copy()

    def observe(self, source, quote, *, now_ms, max_quote_age_ms=3000,
                max_transport_lag_ms=1000, max_spread_bps="20"):
        key = self._key(source)
        bid, ask = _quote(quote)
        if not _integer(now_ms, _MAX_MS):
            raise ValueError("Invalid server clock")
        if not _integer(max_quote_age_ms, 60000) or max_quote_age_ms < 100:
            raise ValueError("Invalid quote age policy")
        if not _integer(max_transport_lag_ms, 60000):
            raise ValueError("Invalid transport policy")
        limit = _money(max_spread_bps, maximum=Decimal("10000"))
        if ask <= bid:
            return _result("CROSSED_OR_LOCKED")
        with localcontext() as ctx:
            ctx.prec = 50
            spread = (ask - bid) / bid * Decimal("10000")
        if spread > limit:
            return _result("EXCESSIVE_SPREAD")
        observed, received = quote["observed_at_ms"], quote["received_at_ms"]
        if not observed <= received <= now_ms:
            return _result("FUTURE_OR_REORDERED_TIME")
        if now_ms - observed > max_quote_age_ms:
            return _result("STALE_QUOTE")
        if received - observed > max_transport_lag_ms:
            return _result("TRANSPORT_DELAY")
        identity_sha = key.split(":", 1)[1]
        quote_sha = _digest({"source": identity_sha, "quote_id": quote["quote_id"]})
        with self.session_factory() as db:
            try:
                # Atomic quote+journal sessions exclusively own their source.
                # A standalone observer must not advance its quote marker while
                # leaving the bound journal at an older checkpoint revision.
                owner_key = "paper-quote-journal-owner:" + key.split(":", 1)[1]
                if db.scalar(select(Record.value).where(Record.key == owner_key)) is not None:
                    return _result("ATOMIC_JOURNAL_OWNS_QUOTE_SOURCE")
                previous_raw = db.scalar(select(Record.value).where(Record.key == key))
                previous = _decode(previous_raw, identity_sha) if previous_raw is not None else None
                if previous is not None:
                    if now_ms < previous["accepted_at_ms"]:
                        return _result("SERVER_CLOCK_REGRESSION")
                    if quote_sha in previous["recent_quote_hashes"]:
                        return _result("REUSED_QUOTE_ID")
                    if quote["sequence"] <= previous["sequence"]:
                        return _result("NON_INCREASING_SEQUENCE")
                    if observed <= previous["observed_at_ms"] or received <= previous["received_at_ms"]:
                        return _result("REPLAYED_QUOTE_TIME")
                revision = 0 if previous is None else previous["revision"] + 1
                if revision > _MAX_SEQ:
                    return _result("REVISION_EXHAUSTED")
                doc = {"version": 1, "identity_sha256": identity_sha, "revision": revision,
                       "sequence": quote["sequence"], "observed_at_ms": observed,
                       "received_at_ms": received, "accepted_at_ms": now_ms,
                       "quote_sha256": quote_sha,
                       "recent_quote_hashes": (previous["recent_quote_hashes"][-63:] if previous else []) + [quote_sha]}
                next_raw = _canonical({**doc, "checksum": _digest(doc)})
                if previous_raw is None:
                    db.execute(insert(Record).values(key=key, value=next_raw))
                else:
                    updated = db.execute(update(Record).where(
                        Record.key == key, Record.value == previous_raw).values(value=next_raw))
                    if updated.rowcount != 1:
                        db.rollback()
                        return _result("CONCURRENT_MARKER_CHANGE")
                db.add(Audit(time=int(time.time()), actor="system",
                             action="paper.quote.observe",
                             detail=_canonical({"source_hash": identity_sha,
                                                "quote_hash": quote_sha, "revision": revision})))
                db.commit()
                return _result("MARKER_RECORDED_NOT_AUTHENTICATED", True, revision)
            except IntegrityError:
                db.rollback()
                return _result("CONCURRENT_MARKER_CHANGE")
