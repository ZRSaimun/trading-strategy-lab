"""SQLite transactional regression suite; PostgreSQL must be tested separately."""
import json
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.db import Base, Record, Audit
from app.paper_journal_store import PaperJournalStore

IDENTITY = {"instrument": "XAUUSD-DEMO-A", "provider": "Demo A", "venue": "Demo OTC",
            "priceSide": "bid-ask", "pointValue": 1}

def checkpoint(identity=IDENTITY, actions=None):
    return json.dumps({"version": 1, "identity": identity, "actions": actions or [],
                       "orders": [], "events": []}, separators=(",", ":"))

@pytest.fixture
def setup(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "paper.db"), connect_args={"timeout": 2})
    Base.metadata.create_all(engine)
    return engine, sessionmaker(engine)


def test_persists_across_store_restarts_and_audits_only_commits(setup):
    engine, factory = setup
    a = PaperJournalStore(factory)
    assert a.load("demo-1") is None
    assert a.compare_and_swap("demo-1", IDENTITY, None, 0, checkpoint())
    b = PaperJournalStore(factory)
    assert b.load("demo-1")["revision"] == 0
    assert b.compare_and_swap("demo-1", IDENTITY, 0, 1, checkpoint(actions=[{"kind": "TEST"}]))
    assert a.load("demo-1")["revision"] == 1
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 2
        assert len(db.scalars(select(Record).where(Record.key.like("paper-journal:%"))).all()) == 1
    engine.dispose()


def test_stale_and_competing_initial_writers_fail_closed(setup):
    _, factory = setup
    a, b = PaperJournalStore(factory), PaperJournalStore(factory)
    assert a.compare_and_swap("same", IDENTITY, None, 0, checkpoint())
    assert not b.compare_and_swap("same", IDENTITY, None, 0, checkpoint())
    assert a.compare_and_swap("same", IDENTITY, 0, 1, checkpoint(actions=[1]))
    assert not b.compare_and_swap("same", IDENTITY, 0, 1, checkpoint(actions=[2]))
    assert a.load("same")["json"] == checkpoint(actions=[1])
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.journal.cas")).all()) == 2


def test_failed_update_transaction_rolls_back_and_retry_is_possible(setup):
    engine, factory = setup
    store = PaperJournalStore(factory)
    assert store.compare_and_swap("crash", IDENTITY, None, 0, checkpoint())
    def interrupt(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("UPDATE records"):
            raise RuntimeError("synthetic interrupted transaction")
    event.listen(engine, "before_cursor_execute", interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        store.compare_and_swap("crash", IDENTITY, 0, 1, checkpoint(actions=[1]))
    event.remove(engine, "before_cursor_execute", interrupt)
    assert store.load("crash")["revision"] == 0
    assert store.compare_and_swap("crash", IDENTITY, 0, 1, checkpoint(actions=[1]))
    assert store.load("crash")["revision"] == 1


def test_source_identity_and_revision_are_not_silently_rewritten(setup):
    _, factory = setup
    store = PaperJournalStore(factory)
    assert store.compare_and_swap("isolation", IDENTITY, None, 0, checkpoint())
    other = {**IDENTITY, "provider": "Other demo"}
    with pytest.raises(ValueError, match="identity mismatch"):
        store.compare_and_swap("isolation", other, 0, 1, checkpoint(other))
    with pytest.raises(ValueError, match="source identity mismatch"):
        store.compare_and_swap("isolation", IDENTITY, 0, 1, checkpoint(other))
    with pytest.raises(ValueError, match="exactly one"):
        store.compare_and_swap("isolation", IDENTITY, 0, 2, checkpoint())
    assert store.load("isolation")["revision"] == 0


def test_corrupt_stored_data_fails_closed(setup):
    _, factory = setup
    store = PaperJournalStore(factory)
    store.compare_and_swap("corrupt", IDENTITY, None, 0, checkpoint())
    key = store._key("corrupt")
    with factory.begin() as db:
        record = db.get(Record, key)
        doc = json.loads(record.value)
        doc["json"] = checkpoint(actions=[{"forged": True}])
        record.value = json.dumps(doc)
    with pytest.raises(ValueError, match="corrupt"):
        store.load("corrupt")
    with pytest.raises(ValueError, match="corrupt"):
        store.compare_and_swap("corrupt", IDENTITY, 0, 1, checkpoint())


def test_rejects_invalid_identifiers_payloads_and_revisions(setup):
    _, factory = setup
    store = PaperJournalStore(factory)
    with pytest.raises(ValueError, match="session ID"):
        store.load("../../secrets")
    with pytest.raises(ValueError, match="byte limit"):
        store.compare_and_swap("size", IDENTITY, None, 0, "x" * 8_000_001)
    with pytest.raises(ValueError, match="JSON"):
        store.compare_and_swap("bad-json", IDENTITY, None, 0, "{invalid")
    with pytest.raises(ValueError, match="revision"):
        store.compare_and_swap("revision", IDENTITY, None, True, checkpoint())
    with pytest.raises(ValueError, match="point value"):
        store.compare_and_swap("wrong", {**IDENTITY, "pointValue": float("nan")}, None, 0, checkpoint())
    assert store.load("size") is None


def test_two_source_isolated_sessions_and_nonfinite_payloads(setup):
    _, factory = setup
    store = PaperJournalStore(factory)
    other = {**IDENTITY, "provider": "Other demo"}
    assert store.compare_and_swap("session-a", IDENTITY, None, 0, checkpoint())
    assert store.compare_and_swap("session-b", other, None, 0, checkpoint(other))
    assert store.load("session-a")["identity"] == IDENTITY
    assert store.load("session-b")["identity"] == other
    with pytest.raises(ValueError, match="JSON"):
        store.compare_and_swap("nan", IDENTITY, None, 0, checkpoint(actions=[float("nan")]))
    with pytest.raises(ValueError, match="collections"):
        store.compare_and_swap("too-many", IDENTITY, None, 0, checkpoint(actions=[0] * 50_001))
    assert store.load("nan") is None
    assert store.load("too-many") is None


def test_duplicate_json_fields_and_exponent_overflow_fail_closed(setup):
    _, factory = setup
    store = PaperJournalStore(factory)
    valid = checkpoint()
    duplicate = valid.replace('"version":1', '"version":1,"version":1')
    nested_duplicate = valid.replace('"pointValue":1', '"pointValue":1,"pointValue":1')
    overflow = valid.replace('"actions":[]', '"actions":[{"quote":1e999}]')
    for index, payload in enumerate((duplicate, nested_duplicate, overflow)):
        with pytest.raises(ValueError, match="JSON"):
            store.compare_and_swap(f"reject-{index}", IDENTITY, None, 0, payload)
        assert store.load(f"reject-{index}") is None
    assert store.compare_and_swap("stored-corrupt", IDENTITY, None, 0, valid)
    key = store._key("stored-corrupt")
    with factory.begin() as db:
        record = db.get(Record, key)
        record.value = record.value.replace('"revision":0', '"revision":0,"revision":0')
    with pytest.raises(ValueError, match="corrupt"):
        store.load("stored-corrupt")
