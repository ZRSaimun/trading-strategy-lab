"""Isolated SQLite acceptance tests; NOT PostgreSQL concurrency certification."""
import json
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import sessionmaker
from app.db import Audit, Base, Record
from app.paper_risk_reservations import PaperRiskReservationStore

@pytest.fixture
def setup(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "risk.db"))
    Base.metadata.create_all(engine)
    yield engine, sessionmaker(engine)
    engine.dispose()

def store(setup):
    return PaperRiskReservationStore(setup[1])

def enabled(s):
    assert s.initialize("paper-acct-0001")
    assert s.set_policy("paper-acct-0001", 0, limit_cash="100.00", kill_switch=False,
                        owner_reviewed=True)

def test_default_is_killed_and_uninitialized_fails_closed(setup):
    s = store(setup)
    assert s.load("paper-acct-0001") is None
    assert not s.reserve("paper-acct-0001", 0, client_order_id="order-00001", risk_cash="1")
    assert s.initialize("paper-acct-0001")
    assert s.load("paper-acct-0001")["kill_switch"] is True
    assert not s.reserve("paper-acct-0001", 0, client_order_id="order-00001", risk_cash="1")
    assert not s.initialize("paper-acct-0001")

def test_owner_policy_and_budget(setup):
    s = store(setup)
    enabled(s)
    with pytest.raises(ValueError, match="owner-reviewed"):
        s.set_policy("paper-acct-0001", 1, limit_cash="200", kill_switch=False)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="40.50")
    assert not s.reserve("paper-acct-0001", 2, client_order_id="order-00002", risk_cash="60")
    assert s.reserve("paper-acct-0001", 2, client_order_id="order-00002", risk_cash="59.50")
    assert s.load("paper-acct-0001")["reserved_cash"] == "100.00"
    assert not s.set_policy("paper-acct-0001", 3, limit_cash="99", kill_switch=True, owner_reviewed=True)

def test_duplicate_order_replay_and_restart(setup):
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="2")
    another = store(setup)
    assert not another.reserve("paper-acct-0001", 2, client_order_id="order-00001", risk_cash="3")
    assert not another.reserve("paper-acct-0001", 1, client_order_id="order-00002", risk_cash="3")
    assert another.load("paper-acct-0001")["reservation_count"] == 1

def test_kill_switch_stops_new_reservations_and_cannot_unblock_without_review(setup):
    s = store(setup)
    enabled(s)
    assert s.engage_kill_switch("paper-acct-0001")
    assert not s.reserve("paper-acct-0001", 2, client_order_id="order-00001", risk_cash="1")
    assert not s.set_policy("paper-acct-0001", 1, limit_cash="100", kill_switch=False, owner_reviewed=True)
    assert s.load("paper-acct-0001")["kill_switch"] is True

def test_bad_money_and_identifier_inputs_rejected(setup):
    s = store(setup)
    enabled(s)
    for amount in ("NaN", "Infinity", "-1", "1e4", "0", "1.000000001", "9999999999999", 2.0):
        with pytest.raises(ValueError):
            s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash=amount)
    with pytest.raises(ValueError):
        s.reserve("paper-acct-0001", 1, client_order_id="../secrets", risk_cash="1")
    with pytest.raises(ValueError):
        s.reserve("paper-acct-0001", True, client_order_id="order-00001", risk_cash="1")

def test_corrupt_checksum_and_duplicate_json_fail_closed(setup):
    s = store(setup)
    enabled(s)
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        record = db.get(Record, key)
        record.value = record.value.replace('"revision":1', '"revision":1,"revision":1')
    with pytest.raises(ValueError, match="corrupt"):
        s.load("paper-acct-0001")
    with pytest.raises(ValueError, match="corrupt"):
        s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="1")

def test_transaction_interruption_rolls_back_state_and_audit(setup):
    engine, factory = setup
    s = store(setup)
    enabled(s)
    def interrupt(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.startswith("INSERT INTO audit"):
            raise RuntimeError("synthetic audit interruption")
    event.listen(engine, "before_cursor_execute", interrupt)
    with pytest.raises(RuntimeError, match="interruption"):
        s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="1")
    event.remove(engine, "before_cursor_execute", interrupt)
    assert s.load("paper-acct-0001")["revision"] == 1
    assert s.load("paper-acct-0001")["reserved_cash"] == "0"
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="1")
    with factory() as db:
        assert len(db.scalars(select(Audit).where(Audit.action == "paper.risk.cas")).all()) == 2

def test_account_isolation_and_no_raw_ids_in_audit(setup):
    s = store(setup)
    enabled(s)
    assert s.initialize("paper-acct-0002")
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="1")
    assert s.load("paper-acct-0002")["kill_switch"] is True
    with setup[1]() as db:
        rows = db.scalars(select(Audit)).all()
        assert all("paper-acct-0001" not in row.detail and "order-00001" not in row.detail for row in rows)


def test_audit_actor_does_not_claim_owner_authentication_and_names_operation(setup):
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="2")
    assert s.engage_kill_switch("paper-acct-0001")
    with setup[1]() as db:
        rows = db.scalars(select(Audit).order_by(Audit.id)).all()
    assert [json.loads(row.detail)["operation"] for row in rows] == [
        "initialize", "policy", "reserve", "emergency_kill"
    ]
    assert all(row.actor == "paper-risk-store" for row in rows)
    assert all("paper-acct-0001" not in row.detail for row in rows)

def test_emergency_stop_cannot_be_reenabled_even_with_current_revision(setup):
    s = store(setup)
    enabled(s)
    assert s.engage_kill_switch("paper-acct-0001")
    killed = s.load("paper-acct-0001")
    assert killed["kill_switch"] is True
    assert killed["emergency_latched"] is True
    assert not s.set_policy("paper-acct-0001", killed["revision"],
                            limit_cash="100", kill_switch=False, owner_reviewed=True)
    assert not s.set_policy("paper-acct-0001", 1,
                            limit_cash="100", kill_switch=False, owner_reviewed=True)
    restarted = store(setup)
    assert restarted.load("paper-acct-0001") == killed
    assert restarted.engage_kill_switch("paper-acct-0001")
    assert restarted.load("paper-acct-0001") == killed
    assert not restarted.reserve("paper-acct-0001", killed["revision"],
                                 client_order_id="order-00009", risk_cash="1")


def test_emergency_stop_latches_an_already_disabled_account(setup):
    s = store(setup)
    assert s.initialize("paper-acct-0001")
    assert s.load("paper-acct-0001")["emergency_latched"] is False
    assert s.engage_kill_switch("paper-acct-0001")
    stopped = s.load("paper-acct-0001")
    assert stopped["revision"] == 1
    assert stopped["emergency_latched"] is True
    assert not s.set_policy("paper-acct-0001", 1, limit_cash="100",
                            kill_switch=False, owner_reviewed=True)


def test_invalid_latch_state_fails_closed_even_with_matching_checksum(setup):
    import hashlib
    s = store(setup)
    assert s.initialize("paper-acct-0001")
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        row = db.get(Record, key)
        envelope = json.loads(row.value)
        envelope["state"]["emergency_latched"] = "false"
        canonical = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":"))
        envelope["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        row.value = json.dumps(envelope)
    with pytest.raises(ValueError, match="corrupt"):
        s.load("paper-acct-0001")
    with pytest.raises(ValueError, match="corrupt"):
        s.engage_kill_switch("paper-acct-0001")
