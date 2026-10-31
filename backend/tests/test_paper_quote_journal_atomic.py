"""Offline synthetic acceptance of atomic quote-marker + paper journal writes."""
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Audit, Base, Record
from app.paper_quote_journal_atomic import AtomicPaperQuoteJournalStore
from app.paper_quote_replay_store import PaperQuoteReplayStore
from app.paper_journal_store import PaperJournalStore

NOW = 1_800_000_000_000
SOURCE = {"account_alias": "test-paper-1", "provider": "TEST", "venue": "TEST-OTC", "instrument": "XAUUSD-TEST"}
IDENTITY = {"instrument": "XAUUSD-TEST", "provider": "TEST", "venue": "TEST-OTC", "priceSide": "bid-ask", "pointValue": 1}


def quote(i=1, **changes):
    return {**{"quote_id": f"quote-id-{i:05d}", "sequence": i,
               "observed_at_ms": NOW + (i - 1) * 100,
               "received_at_ms": NOW + (i - 1) * 100 + 20,
               "bid": "4000.00", "ask": "4000.50"}, **changes}


def checkpoint(tag, history=()):
    return json.dumps({"version": 1, "identity": IDENTITY,
                       "actions": [*history, tag],
                       "orders": [], "events": []}, separators=(",", ":"))


@pytest.fixture
def stores(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "atomic.db"), connect_args={"timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield AtomicPaperQuoteJournalStore(factory), PaperQuoteReplayStore(factory), PaperJournalStore(factory), engine, factory
    engine.dispose()


def append(store, i=1, session_id="paper-session-a", source=SOURCE, expected=None, **kwargs):
    return store.checkpoint(source, quote(i), session_id, IDENTITY, expected,
                            0 if expected is None else expected + 1,
                            checkpoint(f"checkpoint-{i}"), now_ms=NOW + (i - 1) * 100 + 30,
                            **kwargs)


def test_first_checkpoint_is_atomic_unverified_and_never_executes(stores):
    atomic, quotes, journal, _, factory = stores
    result = append(atomic)
    assert result["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    assert result["quote_revision"] == result["journal_revision"] == 0
    assert result["quote_authenticated"] is False
    assert result["journal_fills_verified"] is False
    assert result["paper_order_permitted"] is result["live_order_permitted"] is False
    assert quotes.load_marker(SOURCE)["sequence"] == 1
    assert journal.load("paper-session-a")["revision"] == 0
    with factory() as db:
        rows = db.scalars(select(Record)).all()
        audits = db.scalars(select(Audit)).all()
    assert len(rows) == 4
    assert len(audits) == 1
    assert audits[0].action == "paper.quote_journal.atomic"
    assert "4000.00" not in audits[0].detail
    assert "test-paper-1" not in audits[0].detail


def test_next_checkpoint_updates_both_revisions(stores):
    atomic, quotes, journal, _, _ = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    assert append(atomic, 2, expected=0)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    assert quotes.load_marker(SOURCE)["revision"] == 1
    assert journal.load("paper-session-a")["revision"] == 1


@pytest.mark.parametrize("reason,kwargs", [
    ("REUSED_QUOTE_ID", {"i": 1, "expected": 0}),
    ("JOURNAL_REVISION_OR_IDENTITY_MISMATCH", {"i": 2, "expected": 1}),
    ("JOURNAL_ALREADY_EXISTS", {"i": 2, "expected": None}),
    ("STALE_QUOTE", {"i": 2, "expected": 0, "max_quote_age_ms": 100}),
])
def test_rejections_do_not_partially_advance(stores, reason, kwargs):
    atomic, quotes, journal, _, factory = stores
    append(atomic)
    if reason == "STALE_QUOTE":
        q = quote(2, observed_at_ms=NOW - 1000, received_at_ms=NOW - 980)
        result = atomic.checkpoint(SOURCE, q, "paper-session-a", IDENTITY, 0, 1,
                                   checkpoint("stale"), now_ms=NOW + 130,
                                   max_quote_age_ms=100)
    else:
        result = append(atomic, **kwargs)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == reason
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert journal.load("paper-session-a")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1


def test_account_binding_rejects_cross_account_session(stores):
    atomic, quotes, journal, _, _ = stores
    append(atomic)
    different = {**SOURCE, "account_alias": "other-paper-account"}
    assert append(atomic, 2, source=different, expected=0)["reason"] == "JOURNAL_ACCOUNT_BINDING_MISMATCH"
    assert quotes.load_marker(different) is None
    assert journal.load("paper-session-a")["revision"] == 0


def test_identity_mismatch_fails_before_writing(stores):
    atomic, quotes, journal, _, _ = stores
    with pytest.raises(ValueError, match="identities differ"):
        append(atomic, source={**SOURCE, "venue": "OTHER"})
    assert quotes.load_marker(SOURCE) is None
    assert journal.load("paper-session-a") is None


def test_existing_unbound_journal_requires_manual_reconciliation(stores):
    atomic, quotes, journal, _, _ = stores
    assert journal.compare_and_swap("paper-session-a", IDENTITY, None, 0, checkpoint("prior"))
    result = append(atomic, 2, expected=0)
    assert result["reason"] == "JOURNAL_BINDING_INCOMPLETE"
    assert quotes.load_marker(SOURCE) is None


def test_audit_failure_rolls_back_both_records_and_binding(stores):
    atomic, quotes, journal, engine, factory = stores
    def fail(_conn, _cursor, statement, _params, _context, _many):
        if statement.lstrip().upper().startswith("INSERT INTO AUDIT"):
            raise RuntimeError("synthetic audit failure")
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="audit failure"):
            append(atomic)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert quotes.load_marker(SOURCE) is None
    assert journal.load("paper-session-a") is None
    with factory() as db:
        assert db.scalars(select(Record)).all() == []
        assert db.scalars(select(Audit)).all() == []
    append(atomic)
    event.listen(engine, "before_cursor_execute", fail)
    try:
        with pytest.raises(RuntimeError, match="audit failure"):
            append(atomic, 2, expected=0)
    finally:
        event.remove(engine, "before_cursor_execute", fail)
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert journal.load("paper-session-a")["revision"] == 0


def test_concurrent_initial_writers_only_one_wins(stores):
    atomic, quotes, journal, _, factory = stores
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: append(atomic), range(2)))
    assert sorted(result["status"] for result in results) == [
        "CHECKPOINT_RECORDED_UNVERIFIED", "HOLD_RECONCILIATION"
    ]
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert journal.load("paper-session-a")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1


def test_concurrent_revision_writers_only_one_wins(stores):
    atomic, quotes, journal, _, factory = stores
    append(atomic)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: append(atomic, 2, expected=0), range(2)))
    assert sorted(result["status"] for result in results) == [
        "CHECKPOINT_RECORDED_UNVERIFIED", "HOLD_RECONCILIATION"
    ]
    assert quotes.load_marker(SOURCE)["revision"] == 1
    assert journal.load("paper-session-a")["revision"] == 1
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 2


def test_standalone_journal_cas_cannot_bypass_atomic_binding(stores):
    atomic, quotes, journal, _, factory = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    with factory() as db:
        original_audits = len(db.scalars(select(Audit)).all())

    # Both stale-revision and otherwise-valid standalone writers must fail
    # closed: only the atomic quote+journal path may advance a bound session.
    assert journal.compare_and_swap(
        "paper-session-a", IDENTITY, 0, 1, checkpoint("bypass")
    ) is False
    assert journal.compare_and_swap(
        "paper-session-a", IDENTITY, None, 0, checkpoint("reinitialize")
    ) is False
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert journal.load("paper-session-a")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == original_audits

    # The owner of the bound journal can still atomically advance both records.
    assert append(atomic, 2, expected=0)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    assert quotes.load_marker(SOURCE)["revision"] == 1
    assert journal.load("paper-session-a")["revision"] == 1


def test_unbound_journal_still_supports_standalone_paper_replay(stores):
    atomic, quotes, journal, _, _ = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    assert journal.compare_and_swap(
        "independent-paper-session", IDENTITY, None, 0, checkpoint("initial")
    ) is True
    assert journal.compare_and_swap(
        "independent-paper-session", IDENTITY, 0, 1, checkpoint("next", history=("initial",))
    ) is True
    assert journal.load("independent-paper-session")["revision"] == 1
    assert journal.load("paper-session-a")["revision"] == 0
    assert quotes.load_marker(SOURCE)["revision"] == 0


def test_bound_source_refuses_standalone_quote_observation(stores):
    atomic, quotes, journal, _, factory = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    result = quotes.observe(SOURCE, quote(2), now_ms=NOW + 130)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "ATOMIC_JOURNAL_OWNS_QUOTE_SOURCE"
    assert result["paper_order_permitted"] is result["live_order_permitted"] is False
    assert quotes.load_marker(SOURCE)["revision"] == 0
    assert journal.load("paper-session-a")["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1
    assert append(atomic, 2, expected=0)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"


def test_same_source_cannot_bind_second_paper_journal(stores):
    atomic, quotes, journal, _, factory = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    result = append(atomic, 2, session_id="paper-session-b")
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "QUOTE_SOURCE_ALREADY_BOUND_TO_OTHER_JOURNAL"
    assert journal.load("paper-session-b") is None
    assert journal.load("paper-session-a")["revision"] == 0
    assert quotes.load_marker(SOURCE)["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1
        assert len(db.scalars(select(Record)).all()) == 4


def test_missing_reverse_source_binding_fails_closed(stores):
    atomic, quotes, journal, _, factory = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    from sqlalchemy import delete
    from app.paper_quote_replay_store import PaperQuoteReplayStore
    owner_key = "paper-quote-journal-owner:" + PaperQuoteReplayStore._key(SOURCE).split(":", 1)[1]
    with factory.begin() as db:
        db.execute(delete(Record).where(Record.key == owner_key))
    result = append(atomic, 2, expected=0)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "QUOTE_SOURCE_BINDING_INCOMPLETE"
    assert journal.load("paper-session-a")["revision"] == 0
    assert quotes.load_marker(SOURCE)["revision"] == 0

    # A missing reverse marker must not reopen the standalone quote writer.
    # The surviving forward binding proves that this source is still owned.
    rejected = quotes.observe(SOURCE, quote(2), now_ms=NOW + 130)
    assert rejected["status"] == "HOLD_RECONCILIATION"
    assert rejected["reason"] == "QUOTE_SOURCE_BINDING_INCOMPLETE"
    assert rejected["paper_order_permitted"] is False
    assert rejected["live_order_permitted"] is False
    assert journal.load("paper-session-a")["revision"] == 0
    assert quotes.load_marker(SOURCE)["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1


def test_atomic_refuses_to_adopt_standalone_quote_marker(stores):
    atomic, quotes, journal, _, factory = stores
    assert quotes.observe(SOURCE, quote(1), now_ms=NOW + 30)["status"] == "ACCEPTED_UNVERIFIED"
    before = quotes.load_marker(SOURCE)
    result = append(atomic, 2)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "UNBOUND_QUOTE_MARKER_REQUIRES_RECONCILIATION"
    assert result["paper_order_permitted"] is result["live_order_permitted"] is False
    assert quotes.load_marker(SOURCE) == before
    assert journal.load("paper-session-a") is None
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1
        assert len(db.scalars(select(Record)).all()) == 1


def test_atomic_refuses_legacy_forward_binding_without_reverse_owner(stores):
    atomic, quotes, journal, _, factory = stores
    source_hash = PaperQuoteReplayStore._key(SOURCE).split(":", 1)[1]
    with factory.begin() as db:
        db.add(Record(key="paper-journal-source:" + "a" * 64, value=source_hash))
    result = append(atomic)
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "QUOTE_SOURCE_BINDING_INCOMPLETE"
    assert quotes.load_marker(SOURCE) is None
    assert journal.load("paper-session-a") is None
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 0
        assert len(db.scalars(select(Record)).all()) == 1


def test_missing_reverse_owner_cannot_be_rebound_to_new_atomic_journal(stores):
    atomic, quotes, journal, _, factory = stores
    assert append(atomic)["status"] == "CHECKPOINT_RECORDED_UNVERIFIED"
    from sqlalchemy import delete
    owner_key = "paper-quote-journal-owner:" + PaperQuoteReplayStore._key(SOURCE).split(":", 1)[1]
    with factory.begin() as db:
        db.execute(delete(Record).where(Record.key == owner_key))
    result = append(atomic, 2, session_id="paper-session-b")
    assert result["status"] == "HOLD_RECONCILIATION"
    assert result["reason"] == "QUOTE_SOURCE_BINDING_INCOMPLETE"
    assert journal.load("paper-session-b") is None
    assert journal.load("paper-session-a")["revision"] == 0
    assert quotes.load_marker(SOURCE)["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1
        assert len(db.scalars(select(Record)).all()) == 3
