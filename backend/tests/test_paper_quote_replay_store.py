"""Synthetic offline quote replay marker tests; no broker connectivity."""
from concurrent.futures import ThreadPoolExecutor
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.db import Audit, Base, Record
from app.paper_quote_replay_store import PaperQuoteReplayStore

SOURCE = {"account_alias": "paper-a", "provider": "DemoProvider", "venue": "DEMO-OTC", "instrument": "XAUUSD-DEMO"}
NOW = 1_800_000_000_000

def quote(i=1, **changes):
    value = {"quote_id": f"quote-id-{i:05d}", "sequence": i,
             "observed_at_ms": NOW + (i - 1) * 100,
             "received_at_ms": NOW + (i - 1) * 100 + 20,
             "bid": "4000.00", "ask": "4000.50"}
    return {**value, **changes}

@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "quotes.db"), connect_args={"timeout": 2})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield PaperQuoteReplayStore(factory), engine, factory
    engine.dispose()


def test_accepts_and_persists_without_authorizing_any_order(store):
    obj, _, factory = store
    first = obj.observe(SOURCE, quote(), now_ms=NOW + 30)
    assert first == {"status": "ACCEPTED_UNVERIFIED", "reason": "MARKER_RECORDED_NOT_AUTHENTICATED",
                     "revision": 0, "quote_authenticated": False, "paper_order_permitted": False,
                     "live_order_permitted": False}
    assert PaperQuoteReplayStore(factory).load_marker(SOURCE)["sequence"] == 1
    assert obj.observe(SOURCE, quote(2), now_ms=NOW + 130)["revision"] == 1
    with factory() as db:
        audit = db.scalars(select(Audit).where(Audit.action == "paper.quote.observe")).all()
        assert len(audit) == 2
        assert "paper-a" not in audit[0].detail and "4000" not in audit[0].detail
        raw = db.scalar(select(Record.value))
        assert "paper-a" not in raw and "4000" not in raw and "quote-id" not in raw

@pytest.mark.parametrize("change,reason", [
    ({"ask": "3999.99"}, "CROSSED_OR_LOCKED"),
    ({"ask": "4000.00"}, "CROSSED_OR_LOCKED"),
    ({"ask": "5000"}, "EXCESSIVE_SPREAD"),
    ({"observed_at_ms": NOW - 4000}, "STALE_QUOTE"),
    ({"received_at_ms": NOW + 40}, "FUTURE_OR_REORDERED_TIME"),
    ({"observed_at_ms": NOW + 25}, "FUTURE_OR_REORDERED_TIME"),
    ({"received_at_ms": NOW + 2000}, "FUTURE_OR_REORDERED_TIME"),
])
def test_bad_first_quotes_cannot_advance_marker(store, change, reason):
    obj, _, _ = store
    assert obj.observe(SOURCE, quote(**change), now_ms=NOW + 30)["reason"] == reason
    assert obj.load_marker(SOURCE) is None


def test_transport_lag_and_spread_policy(store):
    obj, _, _ = store
    assert obj.observe(SOURCE, quote(received_at_ms=NOW + 1200), now_ms=NOW + 1300)["reason"] == "TRANSPORT_DELAY"
    assert obj.observe(SOURCE, quote(), now_ms=NOW + 30, max_spread_bps="0.01")["reason"] == "EXCESSIVE_SPREAD"
    assert obj.load_marker(SOURCE) is None

@pytest.mark.parametrize("second,reason", [
    (quote(), "REUSED_QUOTE_ID"),
    (quote(2, quote_id="quote-id-00001"), "REUSED_QUOTE_ID"),
    (quote(1, quote_id="different-quote-1", observed_at_ms=NOW + 100, received_at_ms=NOW + 120), "NON_INCREASING_SEQUENCE"),
    (quote(2, observed_at_ms=NOW), "REPLAYED_QUOTE_TIME"),
    (quote(2, observed_at_ms=NOW + 10, received_at_ms=NOW + 20), "REPLAYED_QUOTE_TIME"),
])
def test_replay_never_advances_state_or_audit(store, second, reason):
    obj, _, factory = store
    assert obj.observe(SOURCE, quote(), now_ms=NOW + 30)["revision"] == 0
    assert obj.observe(SOURCE, second, now_ms=NOW + 130)["reason"] == reason
    assert obj.load_marker(SOURCE)["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1


def test_clock_regression_and_identity_isolation(store):
    obj, _, _ = store
    obj.observe(SOURCE, quote(), now_ms=NOW + 30)
    assert obj.observe(SOURCE, quote(2), now_ms=NOW + 25)["reason"] == "FUTURE_OR_REORDERED_TIME"
    second_source = {**SOURCE, "account_alias": "paper-b"}
    assert obj.observe(second_source, quote(), now_ms=NOW + 30)["revision"] == 0
    assert obj.load_marker(second_source)["identity_sha256"] != obj.load_marker(SOURCE)["identity_sha256"]

@pytest.mark.parametrize("bad", [
    {"bid": 4000}, {"bid": "NaN"}, {"ask": "Infinity"}, {"bid": "0"},
    {"bid": "1e-9999999"}, {"ask": "1e9999999"}, {"sequence": True},
    {"quote_id": "../secret"}, {"observed_at_ms": 1.5}, {"bid": "1" * 100},
])
def test_invalid_schema_rejected_before_database_write(store, bad):
    obj, _, _ = store
    with pytest.raises(ValueError):
        obj.observe(SOURCE, quote(**bad), now_ms=NOW + 30)
    assert obj.load_marker(SOURCE) is None


def test_invalid_policies_and_source_rejected(store):
    obj, _, _ = store
    for policy in ({"max_quote_age_ms": True}, {"max_transport_lag_ms": -1},
                   {"max_spread_bps": 20}, {"max_spread_bps": "NaN"}, {"now_ms": True}):
        with pytest.raises(ValueError):
            obj.observe(SOURCE, quote(), now_ms=NOW + 30, **policy) if "now_ms" not in policy else obj.observe(SOURCE, quote(), **policy)
    with pytest.raises(ValueError):
        obj.observe({**SOURCE, "account_alias": ""}, quote(), now_ms=NOW + 30)


def test_corrupted_state_blocks_progress(store):
    obj, _, factory = store
    obj.observe(SOURCE, quote(), now_ms=NOW + 30)
    with factory.begin() as db:
        record = db.get(Record, obj._key(SOURCE))
        record.value = record.value.replace('"revision":0', '"revision":0,"revision":0')
    with pytest.raises(ValueError, match="corrupt"):
        obj.load_marker(SOURCE)
    with pytest.raises(ValueError, match="corrupt"):
        obj.observe(SOURCE, quote(2), now_ms=NOW + 130)


def test_atomic_audit_rollback(store):
    obj, engine, factory = store
    obj.observe(SOURCE, quote(), now_ms=NOW + 30)
    def fail(_conn, _cursor, statement, _params, _context, _many):
        if statement.startswith("INSERT INTO audit"):
            raise RuntimeError("synthetic audit failure")
    event.listen(engine, "before_cursor_execute", fail)
    with pytest.raises(RuntimeError, match="audit failure"):
        obj.observe(SOURCE, quote(2), now_ms=NOW + 130)
    event.remove(engine, "before_cursor_execute", fail)
    assert obj.load_marker(SOURCE)["revision"] == 0
    assert obj.observe(SOURCE, quote(2), now_ms=NOW + 130)["revision"] == 1
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 2


def test_two_concurrent_first_writers_have_one_winner(store):
    obj, _, factory = store
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: PaperQuoteReplayStore(factory).observe(SOURCE, quote(), now_ms=NOW + 30), range(2)))
    assert sorted(x["status"] for x in results) == ["ACCEPTED_UNVERIFIED", "HOLD_RECONCILIATION"]
    assert obj.load_marker(SOURCE)["revision"] == 0
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 1


def test_recent_nonadjacent_quote_identifier_reuse_is_quarantined(store):
    obj, _, _ = store
    for i in range(1, 67):
        assert obj.observe(SOURCE, quote(i), now_ms=NOW + (i - 1) * 100 + 30)["status"] == "ACCEPTED_UNVERIFIED"
    assert len(obj.load_marker(SOURCE)["recent_quote_hashes"]) == 64
    assert obj.observe(SOURCE, quote(67, quote_id="quote-id-00003"),
                       now_ms=NOW + 6630)["reason"] == "REUSED_QUOTE_ID"
    assert obj.load_marker(SOURCE)["sequence"] == 66
