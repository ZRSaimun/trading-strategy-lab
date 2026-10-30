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


def test_reservation_audit_records_hashed_order_and_exact_budget_without_raw_ids(setup):
    import hashlib
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001",
                     risk_cash="12.12500001")
    with setup[1]() as db:
        rows = db.scalars(select(Audit).where(Audit.action == "paper.risk.cas")
                          .order_by(Audit.id)).all()
    assert len(rows) == 2
    policy, reservation = [json.loads(row.detail) for row in rows]
    assert policy["operation"] == "policy"
    assert policy["limit_cash"] == "100.00"
    assert policy["reservation_count"] == 0
    assert policy["reservation_order_hash"] is None
    assert reservation["operation"] == "reserve"
    assert reservation["limit_cash"] == "100.00"
    assert reservation["reserved_cash"] == "12.12500001"
    assert reservation["reservation_count"] == 1
    assert reservation["reservation_order_hash"] == hashlib.sha256(
        b"order-00001").hexdigest()
    assert all("order-00001" not in row.detail and "paper-acct-0001" not in row.detail
               for row in rows)


def test_rejected_replay_does_not_mutate_reservation_or_emit_success_audit(setup):
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001",
                     risk_cash="25")
    before = s.load("paper-acct-0001")
    with setup[1]() as db:
        audit_count = len(db.scalars(select(Audit)).all())
    assert not s.reserve("paper-acct-0001", before["revision"],
                         client_order_id="order-00001", risk_cash="1")
    assert s.load("paper-acct-0001") == before
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_count


def test_snapshot_reports_exact_remaining_capacity_without_execution_permission(setup):
    s = store(setup)
    enabled(s)
    initial = s.load("paper-acct-0001")
    assert initial["remaining_risk_capacity_cash"] == "100.00"
    assert initial["may_execute_paper_order"] is False
    assert initial["may_execute_real_order"] is False

    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001",
                     risk_cash="0.00000001")
    partial = store(setup).load("paper-acct-0001")
    assert partial["remaining_risk_capacity_cash"] == "99.99999999"
    assert partial["reserved_cash"] == "1E-8"
    assert partial["may_execute_paper_order"] is False

    assert s.reserve("paper-acct-0001", 2, client_order_id="order-00002",
                     risk_cash="99.99999999")
    exhausted = store(setup).load("paper-acct-0001")
    assert exhausted["remaining_risk_capacity_cash"] == "0E-8"
    assert exhausted["may_execute_paper_order"] is False
    assert not s.reserve("paper-acct-0001", 3, client_order_id="order-00003",
                         risk_cash="0.00000001")


def test_killed_and_missing_snapshots_never_grant_paper_execution(setup):
    s = store(setup)
    assert s.load("paper-acct-0001") is None
    assert s.initialize("paper-acct-0001")
    disabled = s.load("paper-acct-0001")
    assert disabled["kill_switch"] is True
    assert disabled["remaining_risk_capacity_cash"] == "0"
    assert disabled["may_execute_paper_order"] is False
    assert s.engage_kill_switch("paper-acct-0001")
    latched = store(setup).load("paper-acct-0001")
    assert latched["emergency_latched"] is True
    assert latched["may_execute_paper_order"] is False


def test_disabled_policy_has_zero_reservable_capacity_despite_accounting_headroom(setup):
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001",
                     risk_cash="25.12500001")
    enabled_snapshot = s.load("paper-acct-0001")
    assert enabled_snapshot["remaining_risk_capacity_cash"] == "74.87499999"
    assert enabled_snapshot["reservable_risk_capacity_cash"] == "74.87499999"
    assert enabled_snapshot["may_execute_paper_order"] is False
    assert s.set_policy("paper-acct-0001", 2, limit_cash="100.00",
                        kill_switch=True, owner_reviewed=True)
    disabled = store(setup).load("paper-acct-0001")
    assert disabled["remaining_risk_capacity_cash"] == "74.87499999"
    assert disabled["reservable_risk_capacity_cash"] == "0"
    assert disabled["may_execute_paper_order"] is False
    assert not s.reserve("paper-acct-0001", disabled["revision"],
                         client_order_id="order-00002", risk_cash="1")


def test_emergency_latch_freezes_even_disabled_policy_mutations_and_audit(setup):
    s = store(setup)
    enabled(s)
    assert s.engage_kill_switch("paper-acct-0001")
    before = store(setup).load("paper-acct-0001")
    with setup[1]() as db:
        count_before = len(db.scalars(select(Audit)).all())
    assert before["emergency_latched"] is True
    assert before["reservable_risk_capacity_cash"] == "0"
    assert not s.set_policy("paper-acct-0001", before["revision"],
                            limit_cash="200", kill_switch=True, owner_reviewed=True)
    assert not s.set_policy("paper-acct-0001", before["revision"],
                            limit_cash="100", kill_switch=False, owner_reviewed=True)
    assert store(setup).load("paper-acct-0001") == before
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == count_before

def test_enabled_zero_cap_persisted_state_fails_closed_even_with_matching_checksum(setup):
    """A recomputed corruption checksum cannot authorize a zero-cap enabled policy."""
    import hashlib
    s = store(setup)
    assert s.initialize("paper-acct-0001")
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        row = db.get(Record, key)
        envelope = json.loads(row.value)
        envelope["state"]["kill_switch"] = False
        # Simulate a malformed imported snapshot whose checksum was recomputed.
        canonical = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":"))
        envelope["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        row.value = json.dumps(envelope)
    with setup[1]() as db:
        audit_count = len(db.scalars(select(Audit)).all())
    with pytest.raises(ValueError, match="corrupt"):
        s.load("paper-acct-0001")
    with pytest.raises(ValueError, match="corrupt"):
        s.reserve("paper-acct-0001", 0, client_order_id="order-00001", risk_cash="1")
    with pytest.raises(ValueError, match="corrupt"):
        s.engage_kill_switch("paper-acct-0001")
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_count


def test_oversized_persisted_risk_envelope_fails_closed_without_audit(setup):
    """Whitespace can inflate a valid-checksum JSON envelope beyond the safe bound."""
    from app.paper_risk_reservations import _MAX_ENVELOPE_BYTES
    s = store(setup)
    assert s.initialize("paper-acct-0001")
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        row = db.get(Record, key)
        # JSON whitespace is legal and leaves the inner state SHA-256 valid.
        row.value = (" " * _MAX_ENVELOPE_BYTES) + row.value
    with setup[1]() as db:
        audit_before = len(db.scalars(select(Audit)).all())
    with pytest.raises(ValueError, match="corrupt"):
        s.load("paper-acct-0001")
    with pytest.raises(ValueError, match="corrupt"):
        s.reserve("paper-acct-0001", 0, client_order_id="order-00001", risk_cash="1")
    with pytest.raises(ValueError, match="corrupt"):
        s.engage_kill_switch("paper-acct-0001")
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_before


def test_maximum_valid_reservation_count_fits_envelope_budget():
    """The size guard must not reject the supported 500-ID account state."""
    import hashlib
    from decimal import Decimal
    from app.paper_risk_reservations import (
        _MAX_ENVELOPE_BYTES, _MAX_RESERVATIONS, _decode, _encode
    )
    state = {
        "version": 2, "revision": 501, "kill_switch": True,
        "emergency_latched": False, "limit_cash": "1",
        "reservations": {
            hashlib.sha256(f"synthetic-order-{i:08d}".encode()).hexdigest(): "0.00000001"
            for i in range(_MAX_RESERVATIONS)
        },
    }
    key = "paper-risk:" + "0" * 64
    raw = _encode(state, key=key)
    assert len(raw.encode("utf-8")) <= _MAX_ENVELOPE_BYTES
    restored, reserved = _decode(raw, key=key)
    assert restored == state
    assert reserved == Decimal("0.00000500")


def test_impossible_reservation_count_revision_fails_closed_with_matching_checksum(setup):
    """Every retained reservation requires its own committed revision."""
    import hashlib
    from app.paper_risk_reservations import _encode
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1, client_order_id="order-00001", risk_cash="1")
    assert s.reserve("paper-acct-0001", 2, client_order_id="order-00002", risk_cash="1")
    assert store(setup).load("paper-acct-0001")["revision"] == 3
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        row = db.get(Record, key)
        envelope = json.loads(row.value)
        assert len(envelope["state"]["reservations"]) == 2
        envelope["state"]["revision"] = 1
        # Even a recomputed (unkeyed) checksum cannot make this state valid.
        canonical = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":"))
        envelope["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        with pytest.raises(ValueError, match="revision"):
            _encode(envelope["state"], key=key)
        row.value = json.dumps(envelope)
    with setup[1]() as db:
        audit_before = len(db.scalars(select(Audit)).all())
    for operation in (
        lambda: s.load("paper-acct-0001"),
        lambda: s.reserve("paper-acct-0001", 1, client_order_id="order-00003", risk_cash="1"),
        lambda: s.engage_kill_switch("paper-acct-0001"),
    ):
        with pytest.raises(ValueError, match="corrupt"):
            operation()
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_before


def test_first_revision_cannot_claim_reservation_with_matching_checksum(setup):
    """An initialized killed account needs a policy transition before any reserve."""
    import hashlib
    from app.paper_risk_reservations import _encode
    s = store(setup)
    enabled(s)
    assert s.reserve("paper-acct-0001", 1,
                     client_order_id="order-00001", risk_cash="1")
    legitimate = s.load("paper-acct-0001")
    assert legitimate["revision"] == 2
    assert legitimate["reservation_count"] == 1
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        record = db.get(Record, key)
        envelope = json.loads(record.value)
        envelope["state"]["revision"] = 1
        canonical = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":"))
        envelope["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        with pytest.raises(ValueError, match="revision"):
            _encode(envelope["state"], key=key)
        record.value = json.dumps(envelope)
    with setup[1]() as db:
        audit_before = len(db.scalars(select(Audit)).all())
    for action in (
        lambda: s.load("paper-acct-0001"),
        lambda: s.set_policy("paper-acct-0001", 1, limit_cash="100",
                             kill_switch=True, owner_reviewed=True),
        lambda: s.reserve("paper-acct-0001", 1,
                          client_order_id="order-00002", risk_cash="1"),
        lambda: s.engage_kill_switch("paper-acct-0001"),
    ):
        with pytest.raises(ValueError, match="corrupt"):
            action()
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_before


def test_valid_risk_envelope_cannot_be_replayed_under_another_account(setup):
    """Even a valid state checksum must not authorize a different paper account."""
    s = store(setup)
    enabled(s)
    assert s.initialize("paper-acct-0002")
    first_key = s._key("paper-acct-0001")
    second_key = s._key("paper-acct-0002")
    with setup[1].begin() as db:
        original = db.get(Record, first_key).value
        # Simulate a mistaken restore/copy into another account record.
        db.get(Record, second_key).value = original
    with setup[1]() as db:
        before = len(db.scalars(select(Audit)).all())
    for action in (
        lambda: s.load("paper-acct-0002"),
        lambda: s.reserve("paper-acct-0002", 1,
                          client_order_id="order-00002", risk_cash="1"),
        lambda: s.engage_kill_switch("paper-acct-0002"),
    ):
        with pytest.raises(ValueError, match="corrupt"):
            action()
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == before
    assert s.load("paper-acct-0001")["kill_switch"] is False


@pytest.mark.parametrize("mutations", [
    {"kill_switch": False, "limit_cash": "100"},
    {"kill_switch": True, "limit_cash": "100"},
    {"emergency_latched": True},
])
def test_zero_revision_state_cannot_claim_policy_or_emergency_latch(setup, mutations):
    """A recomputed checksum cannot invent a policy or emergency event at revision 0."""
    import hashlib
    s = store(setup)
    assert s.initialize("paper-acct-0001")
    key = s._key("paper-acct-0001")
    with setup[1].begin() as db:
        record = db.get(Record, key)
        envelope = json.loads(record.value)
        assert envelope["state"]["revision"] == 0
        envelope["state"].update(mutations)
        canonical = json.dumps(envelope["state"], sort_keys=True, separators=(",", ":"))
        envelope["sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
        record.value = json.dumps(envelope)
    with setup[1]() as db:
        audit_before = len(db.scalars(select(Audit)).all())
    for action in (
        lambda: s.load("paper-acct-0001"),
        lambda: s.set_policy("paper-acct-0001", 0, limit_cash="100",
                             kill_switch=False, owner_reviewed=True),
        lambda: s.reserve("paper-acct-0001", 0,
                          client_order_id="order-00001", risk_cash="1"),
        lambda: s.engage_kill_switch("paper-acct-0001"),
    ):
        with pytest.raises(ValueError, match="corrupt"):
            action()
    with setup[1]() as db:
        assert len(db.scalars(select(Audit)).all()) == audit_before

def test_legitimate_initial_revision_still_allows_first_policy_transition(setup):
    s = store(setup)
    assert s.initialize("paper-acct-0001")
    assert s.load("paper-acct-0001")["revision"] == 0
    assert s.set_policy("paper-acct-0001", 0, limit_cash="100",
                        kill_switch=False, owner_reviewed=True)
    assert s.load("paper-acct-0001")["revision"] == 1
