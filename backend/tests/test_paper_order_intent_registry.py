"""Synthetic, disconnected replay-quarantine tests; no broker or live orders."""
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker

from app.db import Base, Record, Audit
from app.paper_order_intent_registry import PaperOrderIntentRegistry, _key, _encode

A = "paper-account-001"
O = "client-order-001"
H = hashlib.sha256(b"immutable-reviewed-intent").hexdigest()
H2 = hashlib.sha256(b"changed-intent").hexdigest()
NOW = 1_798_000_000_000


@pytest.fixture
def store(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'paper-intent.db'}", connect_args={"timeout": 10})
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    yield PaperOrderIntentRegistry(factory), factory
    engine.dispose()


def audit_rows(factory):
    with factory() as db:
        return list(db.scalars(select(Audit).order_by(Audit.id)))


def test_missing_record_never_approves(store):
    reg, _ = store
    assert reg.load(A, O) is None
    assert reg.mark_outcome_unknown(A, O, review_sha256=H, expected_revision=0, now_ms=NOW) is False


def test_register_is_preview_only(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    snapshot = reg.load(A, O)
    assert snapshot["state"] == "PREVIEW_ONLY"
    assert snapshot["may_execute_real_order"] is False
    assert snapshot["may_execute_paper_order"] is False
    assert snapshot["requires_reconciliation"] is False
    assert len(audit_rows(factory)) == 1


def test_duplicate_same_or_changed_fingerprint_never_reuses_id(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    assert not reg.register(A, O, review_sha256=H, now_ms=NOW + 1)
    assert not reg.register(A, O, review_sha256=H2, now_ms=NOW + 120_000)
    assert len(audit_rows(factory)) == 1
    assert reg.load(A, O)["review_sha256"] == H


def test_restart_and_account_isolation(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    restarted = PaperOrderIntentRegistry(factory)
    assert not restarted.register(A, O, review_sha256=H2, now_ms=NOW + 10)
    assert restarted.register("paper-account-002", O, review_sha256=H, now_ms=NOW)
    assert len(audit_rows(factory)) == 2


def test_unknown_outcome_is_permanent_and_audited(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    assert reg.mark_outcome_unknown(A, O, review_sha256=H, expected_revision=0, now_ms=NOW + 100)
    restarted = PaperOrderIntentRegistry(factory)
    snapshot = restarted.load(A, O)
    assert snapshot["requires_reconciliation"] is True
    assert snapshot["may_execute_real_order"] is False
    assert not restarted.register(A, O, review_sha256=H, now_ms=NOW + 200_000)
    assert not restarted.mark_outcome_unknown(A, O, review_sha256=H, expected_revision=0, now_ms=NOW + 101)
    assert [r.action for r in audit_rows(factory)] == ["paper.intent.register", "paper.intent.quarantine"]


def test_stale_revision_or_wrong_fingerprint_fails_without_audit(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    assert not reg.mark_outcome_unknown(A, O, review_sha256=H2, expected_revision=0, now_ms=NOW + 1)
    assert not reg.mark_outcome_unknown(A, O, review_sha256=H, expected_revision=0, now_ms=NOW - 1)
    assert len(audit_rows(factory)) == 1


@pytest.mark.parametrize("account,order", [(True, O), (A, True), ("short", O), (A, "with spaces")])
def test_invalid_ids_fail_closed(store, account, order):
    reg, _ = store
    with pytest.raises(ValueError):
        reg.register(account, order, review_sha256=H, now_ms=NOW)


@pytest.mark.parametrize("fingerprint,now,ttl", [(H.upper(), NOW, 10), ("x", NOW, 10),
    (H, True, 10), (H, -1, 10), (H, NOW, 0), (H, NOW, 600_001), (H, NOW, True)])
def test_invalid_review_metadata_fails_closed(store, fingerprint, now, ttl):
    reg, _ = store
    with pytest.raises(ValueError):
        reg.register(A, O, review_sha256=fingerprint, now_ms=now, ttl_ms=ttl)


def test_corrupt_state_or_checksum_fails_closed(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    key, _, _ = _key(A, O)
    with factory() as db:
        record = db.get(Record, key)
        doc = json.loads(record.value)
        doc["state"]["state"] = "APPROVED"
        record.value = _encode(doc["state"])
        db.commit()
    with pytest.raises(ValueError, match="corrupt"):
        reg.load(A, O)


def test_duplicate_json_keys_fail_closed(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    key, _, _ = _key(A, O)
    with factory() as db:
        record = db.get(Record, key)
        record.value = '{"state":{},"state":{},"sha256":"x"}'
        db.commit()
    with pytest.raises(ValueError, match="corrupt"):
        reg.load(A, O)


def test_no_cleartext_ids_in_record_or_audit(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    with factory() as db:
        record = db.scalar(select(Record))
        serialized = record.key + record.value + "".join(x.detail for x in audit_rows(factory))
    assert A not in serialized and O not in serialized


def test_audit_failure_rolls_back_registration(store):
    reg, factory = store
    def reject_audit(session, flush_context, instances):
        if any(isinstance(obj, Audit) for obj in session.new):
            raise RuntimeError("injected audit failure")
    event.listen(factory.class_, "before_flush", reject_audit)
    try:
        with pytest.raises(RuntimeError):
            reg.register(A, O, review_sha256=H, now_ms=NOW)
    finally:
        event.remove(factory.class_, "before_flush", reject_audit)
    assert reg.load(A, O) is None
    assert not audit_rows(factory)


def test_audit_failure_rolls_back_quarantine(store):
    reg, factory = store
    assert reg.register(A, O, review_sha256=H, now_ms=NOW)
    def reject_audit(session, flush_context, instances):
        if any(isinstance(obj, Audit) for obj in session.new):
            raise RuntimeError("injected audit failure")
    event.listen(factory.class_, "before_flush", reject_audit)
    try:
        with pytest.raises(RuntimeError):
            reg.mark_outcome_unknown(A, O, review_sha256=H, expected_revision=0, now_ms=NOW + 1)
    finally:
        event.remove(factory.class_, "before_flush", reject_audit)
    assert reg.load(A, O)["state"] == "PREVIEW_ONLY"
    assert len(audit_rows(factory)) == 1


def test_simultaneous_duplicate_registration_only_one_wins(store):
    reg, factory = store
    def register(_):
        return PaperOrderIntentRegistry(factory).register(A, O, review_sha256=H, now_ms=NOW)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(register, range(2)))
    assert sorted(results) == [False, True]
    assert len(audit_rows(factory)) == 1
