"""Opt-in atomic quote-marker + paper-journal checkpoint transaction.

No endpoint, order execution, quote authentication, or migration. The caller
must use a trusted server clock and a separate authenticated broker feed.
This only records UNVERIFIED inputs and never certifies paper fills.
"""
from decimal import Decimal, localcontext
import hashlib
import time

from sqlalchemy import insert, select, update
from sqlalchemy.exc import IntegrityError

from .db import Audit, Record, Session
from .paper_quote_replay_store import (
    _MAX_MS, _MAX_SEQ, _canonical, _decode as decode_quote,
    _digest, _integer, _money, _quote, _source,
)
from .paper_journal_store import (
    PaperJournalStore, _checkpoint, _decode as decode_journal,
    _identity, _revision,
)


def _decision(reason, *, accepted=False, quote_revision=None, journal_revision=None):
    return {
        "status": "CHECKPOINT_RECORDED_UNVERIFIED" if accepted else "HOLD_RECONCILIATION",
        "reason": reason,
        "quote_revision": quote_revision,
        "journal_revision": journal_revision,
        "quote_authenticated": False,
        "journal_fills_verified": False,
        "paper_order_permitted": False,
        "live_order_permitted": False,
    }


class AtomicPaperQuoteJournalStore:
    """One transaction for quote replay advancement and journal checkpoint CAS.

    Journal session IDs are permanently bound to a hashed quote source, which
    includes the account alias. Independent journal/quote writers may race;
    full-value CAS or unique inserts must then fail closed.
    """

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    def checkpoint(self, source, quote, session_id, journal_identity,
                   expected_journal_revision, next_journal_revision, checkpoint_json,
                   *, now_ms, max_quote_age_ms=3000, max_transport_lag_ms=1000,
                   max_spread_bps="20"):
        source_hash = _source(source)
        quote_key = "paper-quote:" + source_hash
        journal_key = PaperJournalStore._key(session_id)
        binding_key = "paper-journal-source:" + hashlib.sha256(
            session_id.encode("ascii")
        ).hexdigest()
        _identity(journal_identity)
        if any(source[k] != journal_identity[k] for k in ("provider", "venue", "instrument")):
            raise ValueError("Quote and journal source identities differ")
        if expected_journal_revision is not None and not _revision(expected_journal_revision):
            raise ValueError("Invalid expected journal revision")
        if (not _revision(next_journal_revision) or next_journal_revision !=
                (0 if expected_journal_revision is None else expected_journal_revision + 1)):
            raise ValueError("Journal revision must advance by one")
        _checkpoint(checkpoint_json, journal_identity)
        bid, ask = _quote(quote)
        if not _integer(now_ms, _MAX_MS):
            raise ValueError("Invalid server clock")
        if not _integer(max_quote_age_ms, 60000) or max_quote_age_ms < 100:
            raise ValueError("Invalid quote age policy")
        if not _integer(max_transport_lag_ms, 60000):
            raise ValueError("Invalid transport policy")
        limit = _money(max_spread_bps, maximum=Decimal("10000"))
        if ask <= bid:
            return _decision("CROSSED_OR_LOCKED")
        with localcontext() as ctx:
            ctx.prec = 50
            spread = (ask - bid) / bid * Decimal("10000")
        if spread > limit:
            return _decision("EXCESSIVE_SPREAD")
        observed, received = quote["observed_at_ms"], quote["received_at_ms"]
        if not observed <= received <= now_ms:
            return _decision("FUTURE_OR_REORDERED_TIME")
        if now_ms - observed > max_quote_age_ms:
            return _decision("STALE_QUOTE")
        if received - observed > max_transport_lag_ms:
            return _decision("TRANSPORT_DELAY")

        quote_hash = _digest({"source": source_hash, "quote_id": quote["quote_id"]})
        journal_digest = hashlib.sha256(checkpoint_json.encode("utf-8")).hexdigest()
        journal_next = _canonical({
            "revision": next_journal_revision, "identity": journal_identity,
            "json": checkpoint_json, "sha256": journal_digest,
        })

        with self.session_factory() as db:
            try:
                quote_raw = db.scalar(select(Record.value).where(Record.key == quote_key))
                journal_raw = db.scalar(select(Record.value).where(Record.key == journal_key))
                binding = db.scalar(select(Record.value).where(Record.key == binding_key))
                previous_quote = decode_quote(quote_raw, source_hash) if quote_raw is not None else None
                previous_journal = decode_journal(journal_raw) if journal_raw is not None else None

                if binding is not None and binding != source_hash:
                    return _decision("JOURNAL_ACCOUNT_BINDING_MISMATCH")
                if (journal_raw is None) != (binding is None):
                    return _decision("JOURNAL_BINDING_INCOMPLETE")
                if journal_raw is not None and quote_raw is None:
                    return _decision("QUOTE_MARKER_MISSING")
                if expected_journal_revision is None:
                    if previous_journal is not None:
                        return _decision("JOURNAL_ALREADY_EXISTS")
                elif (previous_journal is None or
                      previous_journal["identity"] != journal_identity or
                      previous_journal["revision"] != expected_journal_revision):
                    return _decision("JOURNAL_REVISION_OR_IDENTITY_MISMATCH")

                if previous_quote is not None:
                    if now_ms < previous_quote["accepted_at_ms"]:
                        return _decision("SERVER_CLOCK_REGRESSION")
                    if quote_hash in previous_quote["recent_quote_hashes"]:
                        return _decision("REUSED_QUOTE_ID")
                    if quote["sequence"] <= previous_quote["sequence"]:
                        return _decision("NON_INCREASING_SEQUENCE")
                    if (observed <= previous_quote["observed_at_ms"] or
                            received <= previous_quote["received_at_ms"]):
                        return _decision("REPLAYED_QUOTE_TIME")
                quote_revision = 0 if previous_quote is None else previous_quote["revision"] + 1
                if quote_revision > _MAX_SEQ:
                    return _decision("QUOTE_REVISION_EXHAUSTED")
                quote_doc = {
                    "version": 1, "identity_sha256": source_hash, "revision": quote_revision,
                    "sequence": quote["sequence"], "observed_at_ms": observed,
                    "received_at_ms": received, "accepted_at_ms": now_ms,
                    "quote_sha256": quote_hash,
                    "recent_quote_hashes": (
                        previous_quote["recent_quote_hashes"][-63:] if previous_quote else []
                    ) + [quote_hash],
                }
                quote_next = _canonical({**quote_doc, "checksum": _digest(quote_doc)})

                if quote_raw is None:
                    db.execute(insert(Record).values(key=quote_key, value=quote_next))
                else:
                    changed = db.execute(update(Record).where(
                        Record.key == quote_key, Record.value == quote_raw
                    ).values(value=quote_next))
                    if changed.rowcount != 1:
                        db.rollback()
                        return _decision("CONCURRENT_QUOTE_CHANGE")

                if journal_raw is None:
                    db.execute(insert(Record).values(key=journal_key, value=journal_next))
                    db.execute(insert(Record).values(key=binding_key, value=source_hash))
                else:
                    changed = db.execute(update(Record).where(
                        Record.key == journal_key, Record.value == journal_raw
                    ).values(value=journal_next))
                    if changed.rowcount != 1:
                        db.rollback()
                        return _decision("CONCURRENT_JOURNAL_CHANGE")

                db.add(Audit(time=int(time.time()), actor="system",
                             action="paper.quote_journal.atomic",
                             detail=_canonical({
                                 "quote_source_hash": source_hash,
                                 "quote_hash": quote_hash,
                                 "quote_revision": quote_revision,
                                 "journal_session_hash": journal_key.split(":", 1)[1],
                                 "journal_sha256": journal_digest,
                                 "journal_revision": next_journal_revision,
                             })))
                db.commit()
                return _decision("ATOMIC_CHECKPOINT_NOT_AUTHENTICATED", accepted=True,
                                 quote_revision=quote_revision,
                                 journal_revision=next_journal_revision)
            except IntegrityError:
                db.rollback()
                return _decision("CONCURRENT_INSERT_CONFLICT")
