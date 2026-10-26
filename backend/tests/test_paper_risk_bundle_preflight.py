"""Synthetic, offline cross-store preflight tests. No orders or broker network."""
import hashlib

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, Record, Audit
from app.paper_daily_loss_breaker import PaperDailyLossBreaker
from app.paper_order_intent_registry import PaperOrderIntentRegistry
from app.paper_quote_replay_store import PaperQuoteReplayStore
from app.paper_risk_bundle_preflight import PaperRiskBundlePreflight

ACCOUNT = "paper-account-001"
ORDER = "client-order-001"
SOURCE = {"account_alias": ACCOUNT, "provider": "DemoProvider",
          "venue": "DEMO-OTC", "instrument": "XAUUSD-DEMO"}
DAY = "2026-10-26"
T0 = 1792972800000
REVIEW = hashlib.sha256(b"one immutable review").hexdigest()


@pytest.fixture
def store(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "risk-bundle.db"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield PaperRiskBundlePreflight(factory), factory, engine
    engine.dispose()


def seed(factory, *, daily=True, quote=True, intent=True, loss_reserved="0"):
    if daily:
        breaker = PaperDailyLossBreaker(factory)
        assert breaker.initialize(ACCOUNT, DAY, "GBP", "100")
        assert breaker.observe(ACCOUNT, DAY, sequence=1, observed_ms=T0 + 2000,
                               now_ms=T0 + 2020, realized="0", unrealized="0",
                               reserved=loss_reserved)
    if quote:
        marker = PaperQuoteReplayStore(factory)
        observed = marker.observe(SOURCE, {
            "quote_id": "quote-id-0001", "sequence": 1,
            "observed_at_ms": T0 + 2000, "received_at_ms": T0 + 2020,
            "bid": "4000", "ask": "4000.5",
        }, now_ms=T0 + 2030)
        assert observed["status"] == "ACCEPTED_UNVERIFIED"
    if intent:
        assert PaperOrderIntentRegistry(factory).register(
            ACCOUNT, ORDER, review_sha256=REVIEW, now_ms=T0 + 2000, ttl_ms=30000)


def inspect(preflight, **changes):
    args = {"review_sha256": REVIEW, "now_ms": T0 + 2050}
    args.update(changes)
    return preflight.inspect(ACCOUNT, ORDER, SOURCE, **args)


def test_missing_evidence_always_holds(store):
    preflight, _, _ = store
    r = inspect(preflight)
    assert r["reason"] == "INCOMPLETE_RISK_EVIDENCE"
    assert r["checks"]["intent_present"] is False
    assert not r["may_execute_real_order"] and not r["may_execute_paper_order"]


def test_three_store_snapshot_coherent_but_never_authorizes(store):
    preflight, factory, engine = store
    seed(factory)
    statements = []
    def record(_conn, _cursor, statement, _params, _context, _executemany):
        if "SELECT" in statement.upper():
            statements.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        r = inspect(preflight)
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(statements) == 1
    assert r["observations_coherent_unverified"] is True
    assert r["reason"] == "UNAUTHENTICATED_EVIDENCE"
    assert r["broker_authenticated"] is False
    assert r["account_inventory_reconciled"] is False
    assert r["human_order_approval_verified"] is False
    assert r["may_execute_real_order"] is False
    assert r["may_execute_paper_order"] is False
    assert len(r["evidence_fingerprint_sha256"]) == 64
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == 3


@pytest.mark.parametrize("missing", ["daily", "quote", "intent"])
def test_each_missing_store_fails_closed(store, missing):
    preflight, factory, _ = store
    seed(factory, **{missing: False})
    assert inspect(preflight)["reason"] == "INCOMPLETE_RISK_EVIDENCE"


def test_expired_review_and_mismatched_digest_hold(store):
    preflight, factory, _ = store
    seed(factory)
    assert inspect(preflight, now_ms=T0 + 32001)["checks"]["intent_current"] is False
    assert inspect(preflight, review_sha256="0" * 64)["checks"]["intent_digest_matches"] is False


def test_stale_quote_and_daily_observation_hold(store):
    preflight, factory, _ = store
    seed(factory)
    stale = inspect(preflight, now_ms=T0 + 13000)
    assert stale["checks"]["quote_observation_fresh"] is False
    assert stale["checks"]["daily_loss_observation_fresh"] is False


def test_daily_loss_latch_and_unknown_order_hold(store):
    preflight, factory, _ = store
    seed(factory, loss_reserved="100")
    assert inspect(preflight)["checks"]["daily_loss_latch_clear_unverified"] is False
    reg = PaperOrderIntentRegistry(factory)
    assert reg.mark_outcome_unknown(ACCOUNT, ORDER, review_sha256=REVIEW,
                                    expected_revision=0, now_ms=T0 + 2040)
    assert inspect(preflight)["checks"]["intent_is_preview_only"] is False


def test_atomic_quote_binding_requires_reconciliation(store):
    preflight, factory, _ = store
    seed(factory)
    quote_key = PaperQuoteReplayStore._key(SOURCE)
    with factory.begin() as db:
        db.add(Record(key="paper-quote-journal-owner:" + quote_key.split(":", 1)[1],
                      value="paper-journal:unverified"))
    assert inspect(preflight)["checks"]["quote_source_not_bound_to_atomic_journal"] is False


def test_corrupt_store_fails_closed_without_adding_audit(store):
    preflight, factory, _ = store
    seed(factory)
    with factory.begin() as db:
        rec = db.get(Record, PaperDailyLossBreaker._key(ACCOUNT, DAY))
        rec.value = rec.value.replace('"revision":1', '"revision":1,"revision":1')
    with factory() as db:
        before = len(db.scalars(select(Audit)).all())
    r = inspect(preflight)
    assert r["reason"] == "CORRUPT_RISK_EVIDENCE"
    assert not r["observations_coherent_unverified"]
    with factory() as db:
        assert len(db.scalars(select(Audit)).all()) == before


def test_oversized_state_fails_before_json_parse(store):
    preflight, factory, _ = store
    seed(factory)
    with factory.begin() as db:
        db.get(Record, PaperQuoteReplayStore._key(SOURCE)).value = "x" * 16385
    assert inspect(preflight)["reason"] == "CORRUPT_RISK_EVIDENCE"


@pytest.mark.parametrize("kwargs", [
    {"now_ms": True}, {"now_ms": -1}, {"max_quote_age_ms": 3001},
    {"max_loss_age_ms": 10001}, {"review_sha256": "not-a-digest"},
    {"max_quote_age_ms": True},
])
def test_invalid_input_fails_closed(store, kwargs):
    preflight, _, _ = store
    with pytest.raises(ValueError):
        inspect(preflight, **kwargs)


def test_cross_account_quote_source_rejected(store):
    preflight, factory, _ = store
    seed(factory)
    with pytest.raises(ValueError, match="must match"):
        preflight.inspect(ACCOUNT, ORDER, {**SOURCE, "account_alias": "another-account"},
                          review_sha256=REVIEW, now_ms=T0 + 2050)


def test_no_secret_or_raw_alias_in_report(store):
    preflight, factory, _ = store
    seed(factory)
    output = str(inspect(preflight))
    assert ACCOUNT not in output and ORDER not in output
    assert "4000" not in output
