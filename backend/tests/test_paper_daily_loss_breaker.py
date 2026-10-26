"""Synthetic SQLite tests. PostgreSQL concurrency must be separately accepted."""
import json
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.db import Base, Record, Audit
from app.paper_daily_loss_breaker import PaperDailyLossBreaker

DAY = "2026-10-24"
T0 = 1792800000000  # UTC midnight 2026-10-24

@pytest.fixture
def setup(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "loss.db"))
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(engine)
    engine.dispose()


def observed(store, *, sequence=1, observed_ms=T0 + 1000, now_ms=T0 + 1100,
             realized="-50", unrealized="-20", reserved="20", day=DAY):
    return store.observe("demo", day, sequence=sequence, observed_ms=observed_ms,
                         now_ms=now_ms, realized=realized, unrealized=unrealized,
                         reserved=reserved)


def test_latches_at_cap_and_never_clears_after_recovery(setup):
    _, factory = setup
    store = PaperDailyLossBreaker(factory)
    assert store.initialize("demo", DAY, "GBP", "100")
    a = observed(store)
    assert a["peak_loss"] == "90" and not a["latched"]
    b = observed(store, sequence=2, observed_ms=T0 + 1200, now_ms=T0 + 1250, reserved="30")
    assert b["latched"] and b["peak_loss"] == "100"
    c = observed(store, sequence=3, observed_ms=T0 + 1300, now_ms=T0 + 1400, realized="500", unrealized="0", reserved="0")
    assert c["latched"] and c["peak_loss"] == "100"
    assert not c["may_execute_real_order"] and not c["may_execute_paper_order"]
    assert PaperDailyLossBreaker(factory).load("demo", DAY)["latched"]


def test_duplicate_initialization_cannot_reset_or_change_cap(setup):
    _, factory = setup
    s = PaperDailyLossBreaker(factory)
    assert s.initialize("demo", DAY, "GBP", "100")
    assert not s.initialize("demo", DAY, "USD", "100000")
    assert s.load("demo", DAY)["currency"] == "GBP"
    assert s.load("demo", DAY)["cap"] == "100"


def test_replay_future_stale_and_boolean_sequence_rejected(setup):
    _, factory = setup
    s = PaperDailyLossBreaker(factory)
    s.initialize("demo", DAY, "GBP", "100")
    observed(s)
    for args in ({"sequence": 1, "observed_ms": T0 + 2000, "now_ms": T0 + 2100},
                 {"sequence": 2, "observed_ms": T0 + 1000, "now_ms": T0 + 1100},
                 {"sequence": 2, "observed_ms": T0 + 3000, "now_ms": T0 + 2000},
                 {"sequence": 2, "observed_ms": T0 + 2000, "now_ms": T0 + 15000},
                 {"sequence": True, "observed_ms": T0 + 2000, "now_ms": T0 + 2100}):
        with pytest.raises(ValueError):
            observed(s, **args)
    assert s.load("demo", DAY)["revision"] == 1
    with pytest.raises(ValueError, match="UTC day"):
        observed(s, sequence=3, observed_ms=T0 + 86_400_000, now_ms=T0 + 86_400_100)


def test_strict_money_and_invalid_identity_fail_closed(setup):
    _, factory = setup
    s = PaperDailyLossBreaker(factory)
    for cap in ("NaN", "1e9", "0", "-1", "1.123456789", 100, "1000000000000001"):
        with pytest.raises(ValueError):
            s.initialize("demo", DAY, "GBP", cap)
    with pytest.raises(ValueError):
        s.initialize("../../secret", DAY, "GBP", "100")
    with pytest.raises(ValueError):
        s.initialize("demo", "2026-02-30", "GBP", "100")
    s.initialize("demo", DAY, "GBP", "100")
    for value in ("NaN", "1e999", "-0.01", "2.000000000", 10):
        with pytest.raises(ValueError):
            observed(s, reserved=value)
    assert s.load("demo", DAY)["revision"] == 0
    with pytest.raises(ValueError, match="Aggregate paper loss"):
        observed(s, realized="-1000000000000000", unrealized="-1000000000000000",
                 reserved="1000000000000000")
    assert s.load("demo", DAY)["revision"] == 0


def test_isolated_days_and_accounts_and_audit(setup):
    _, factory = setup
    s = PaperDailyLossBreaker(factory)
    assert s.initialize("demo", DAY, "GBP", "100")
    assert s.initialize("demo", "2026-10-25", "GBP", "100")
    assert s.initialize("another", DAY, "GBP", "100")
    observed(s, reserved="40")
    assert s.load("demo", DAY)["latched"]
    assert not s.load("demo", "2026-10-25")["latched"]
    assert not s.load("another", DAY)["latched"]
    with factory() as db:
        logs = db.scalars(select(Audit).where(Audit.action.like("paper.loss.%"))).all()
        assert len(logs) == 4
        assert all("demo" not in log.detail for log in logs)
        assert all(log.actor == "system" for log in logs)


def test_corruption_and_duplicate_json_keys_rejected(setup):
    _, factory = setup
    s = PaperDailyLossBreaker(factory)
    s.initialize("demo", DAY, "GBP", "100")
    with factory.begin() as db:
        rec = db.get(Record, s._key("demo", DAY))
        rec.value = rec.value.replace('"revision":0', '"revision":0,"revision":0')
    with pytest.raises(ValueError, match="Corrupt"):
        s.load("demo", DAY)
    with pytest.raises(ValueError, match="Corrupt"):
        observed(s)


def test_failed_audit_insert_rolls_back_state(setup):
    engine, factory = setup
    s = PaperDailyLossBreaker(factory)
    s.initialize("demo", DAY, "GBP", "100")
    def interrupt(_conn, _cursor, statement, _params, _context, _executemany):
        if "INSERT INTO audit" in statement:
            raise RuntimeError("synthetic audit failure")
    event.listen(engine, "before_cursor_execute", interrupt)
    with pytest.raises(RuntimeError, match="audit failure"):
        observed(s)
    event.remove(engine, "before_cursor_execute", interrupt)
    assert s.load("demo", DAY)["revision"] == 0
    assert observed(s)["revision"] == 1


def test_missing_policy_never_initializes_implicitly(setup):
    _, factory = setup
    s = PaperDailyLossBreaker(factory)
    assert s.load("demo", DAY) is None
    with pytest.raises(ValueError, match="not initialized"):
        observed(s)
    assert s.load("demo", DAY) is None


@pytest.mark.parametrize("changes", [
    {"day": "2026-10-25"},
    {"sequence": 1},
    {"observed_ms": T0 + 1000},
    {"realized": "1"},
])
def test_initial_record_substitution_and_fake_observation_fail_closed(setup, changes):
    _, factory = setup
    store = PaperDailyLossBreaker(factory)
    assert store.initialize("demo", DAY, "GBP", "100")
    with factory.begin() as db:
        record = db.get(Record, store._key("demo", DAY))
        state = json.loads(record.value)
        state.update(changes)
        record.value = json.dumps(state)
    with pytest.raises(ValueError, match="Corrupt"):
        store.load("demo", DAY)
    with pytest.raises(ValueError, match="Corrupt"):
        observed(store)


@pytest.mark.parametrize("changes", [
    {"day": "2026-10-25"},
    {"revision": 2},
    {"sequence": 0},
    {"observed_ms": 0},
    {"observed_ms": T0 + 86_400_000},
])
def test_observed_record_corruption_cannot_clear_breaker(setup, changes):
    _, factory = setup
    store = PaperDailyLossBreaker(factory)
    assert store.initialize("demo", DAY, "GBP", "100")
    assert observed(store, reserved="40")["latched"]
    with factory.begin() as db:
        record = db.get(Record, store._key("demo", DAY))
        state = json.loads(record.value)
        state.update(changes)
        record.value = json.dumps(state)
    with pytest.raises(ValueError, match="Corrupt"):
        store.load("demo", DAY)
    with pytest.raises(ValueError, match="Corrupt"):
        observed(store, sequence=2, observed_ms=T0 + 2000, now_ms=T0 + 2100)


@pytest.mark.parametrize("version", [True, 1.0, "1", None, 2])
def test_corrupt_version_cannot_masquerade_as_daily_loss_policy(setup, version):
    _, factory = setup
    store = PaperDailyLossBreaker(factory)
    assert store.initialize("demo", DAY, "GBP", "100")
    with factory.begin() as db:
        record = db.get(Record, store._key("demo", DAY))
        doc = json.loads(record.value)
        doc["version"] = version
        record.value = json.dumps(doc)
    with pytest.raises(ValueError, match="Corrupt"):
        store.load("demo", DAY)
    with pytest.raises(ValueError, match="Corrupt"):
        observed(store)
    with factory() as db:
        assert db.scalar(select(Audit).where(Audit.action == "paper.loss.observe")) is None


@pytest.mark.parametrize("padding", [
    " " * 9000,
    "\t" * 9000,
])
def test_oversized_stored_daily_loss_state_fails_before_json_parse(setup, padding):
    _, factory = setup
    store = PaperDailyLossBreaker(factory)
    assert store.initialize("demo", DAY, "GBP", "100")
    with factory.begin() as db:
        record = db.get(Record, store._key("demo", DAY))
        # Whitespace after a JSON object is valid JSON; it must not evade the
        # encoded-byte bound just because its parsed object is small.
        record.value += padding
    with pytest.raises(ValueError, match="Corrupt"):
        store.load("demo", DAY)
    with pytest.raises(ValueError, match="Corrupt"):
        observed(store)
    with factory() as db:
        assert db.scalar(select(Audit).where(Audit.action == "paper.loss.observe")) is None
