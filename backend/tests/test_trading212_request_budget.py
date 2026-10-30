"""Synthetic-only offline durable Trading 212 account read-budget tests."""
import os
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from app import trading212_request_budget as budget

SCOPE = "a" * 64
RIGHTS = "b" * 64
ENTITLEMENT = "c" * 64
DAY = "2026-10-26"
TIME = 1793037600


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    directory = tmp_path / "private"
    directory.mkdir(mode=0o700)
    os.chmod(directory, 0o700)
    db = directory / "quota.sqlite"
    monkeypatch.setattr(budget.time, "time", lambda: TIME)
    assert budget._clock()[1] == DAY
    return str(db)


def provision(db, **kwargs):
    args = dict(account_scope_sha256=SCOPE, environment="DEMO", account_type="INVEST",
                utc_day=DAY, max_requests=3, rights_evidence_sha256=RIGHTS,
                entitlement_evidence_sha256=ENTITLEMENT, owner_confirmed=True)
    args.update(kwargs)
    return budget.provision_trading212_read_budget(db, **args)


def reserve(db, id="1" * 32, **kwargs):
    args = dict(request_id=id, endpoint="instruments", account_scope_sha256=SCOPE,
                environment="DEMO", account_type="INVEST")
    args.update(kwargs)
    return budget.reserve_trading212_read(db, **args)


def test_missing_budget_default_deny(ledger):
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger)
    assert not Path(ledger).exists()


def test_private_file_and_no_network(ledger):
    provision(ledger)
    assert os.stat(ledger).st_mode & 0o077 == 0
    result = reserve(ledger)
    assert result["status"] == "RESERVED_NOT_SENT"
    assert result["may_execute_order"] is False
    assert result["market_data_feed"] is False
    assert result["account_quota_verified"] is False
    assert result["safe_to_make_another_request"] is False


def test_owner_and_immutable_policy(ledger):
    with pytest.raises(budget.BrokerBudgetError): provision(ledger, owner_confirmed=False)
    provision(ledger)
    provision(ledger)
    for args in ({"max_requests": 4}, {"account_scope_sha256": "d"*64},
                 {"account_type": "STOCKS_ISA"}, {"environment": "LIVE"}):
        with pytest.raises(budget.BrokerBudgetError): provision(ledger, **args)


def test_daily_limit_and_spacing(ledger, monkeypatch):
    provision(ledger, max_requests=2)
    reserve(ledger)
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger, "2"*32)
    monkeypatch.setattr(budget.time, "time", lambda: TIME+60)
    reserve(ledger, "2"*32)
    monkeypatch.setattr(budget.time, "time", lambda: TIME+120)
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger, "3"*32)


def test_duplicate_rejected_even_later(ledger, monkeypatch):
    provision(ledger)
    reserve(ledger)
    monkeypatch.setattr(budget.time, "time", lambda: TIME+90)
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger)


def test_clock_rollback_denied(ledger, monkeypatch):
    provision(ledger)
    reserve(ledger)
    monkeypatch.setattr(budget.time, "time", lambda: TIME-300)
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger, "2"*32)


def test_scope_and_endpoint_denied(ledger):
    provision(ledger)
    for kwargs in ({"account_scope_sha256": "d"*64}, {"environment": "LIVE"},
                   {"account_type": "STOCKS_ISA"}, {"endpoint": "orders"},
                   {"request_id": "bad"}, {"endpoint": []}):
        with pytest.raises(budget.BrokerBudgetError): reserve(ledger, **kwargs)


def test_concurrent_only_one_reservation(ledger):
    provision(ledger)
    def attempt(i):
        try:
            reserve(ledger, f"{i:032x}")
            return True
        except budget.BrokerBudgetError:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(attempt, range(1, 9))) == 1
    with sqlite3.connect(ledger) as conn:
        assert conn.execute("SELECT COUNT(*) FROM request_reservation").fetchone()[0] == 1


def test_symlink_hardlink_and_public_directory_denied(ledger):
    provision(ledger)
    link = str(Path(ledger).with_name("link.sqlite"))
    os.symlink(ledger, link)
    with pytest.raises(budget.BrokerBudgetError): reserve(link)
    os.unlink(link)
    hard = str(Path(ledger).with_name("hard.sqlite"))
    os.link(ledger, hard)
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger)
    os.unlink(hard)
    os.chmod(Path(ledger).parent, 0o755)
    with pytest.raises(budget.BrokerBudgetError): reserve(ledger)


def test_invalid_provision_does_not_create(ledger):
    for kwargs in ({"utc_day": "2026-10-27"}, {"max_requests": True},
                   {"max_requests": 51}, {"rights_evidence_sha256": "BAD"}):
        with pytest.raises(budget.BrokerBudgetError): provision(ledger, **kwargs)
    assert not Path(ledger).exists()


def test_budgeted_wrapper_denies_without_provision(ledger, monkeypatch):
    from app import trading212_readonly
    calls = []
    monkeypatch.setattr(trading212_readonly, "fetch_trading212_readonly", lambda **kw: calls.append(kw))
    with pytest.raises(budget.BrokerBudgetError):
        budget.fetch_budgeted_trading212_readonly(
            db_path=ledger, request_id="1"*32, account_scope_sha256=SCOPE,
            endpoint="instruments", account_type="INVEST", environment="DEMO",
            api_key="dummy", api_secret="dummy")
    assert not calls


def test_budgeted_wrapper_consumes_before_broker_failure(ledger, monkeypatch):
    from app import trading212_readonly
    provision(ledger)
    calls = []
    def fake(**kwargs):
        calls.append(kwargs["endpoint"])
        raise trading212_readonly.ReadOnlyBrokerError("Broker read refused or unavailable")
    monkeypatch.setattr(trading212_readonly, "fetch_trading212_readonly", fake)
    with pytest.raises(trading212_readonly.ReadOnlyBrokerError):
        budget.fetch_budgeted_trading212_readonly(
            db_path=ledger, request_id="1"*32, account_scope_sha256=SCOPE,
            endpoint="instruments", account_type="INVEST", environment="DEMO",
            api_key="dummy", api_secret="dummy")
    assert calls == ["instruments"]
    with sqlite3.connect(ledger) as conn:
        assert conn.execute("SELECT COUNT(*) FROM request_reservation").fetchone()[0] == 1
    with pytest.raises(budget.BrokerBudgetError):
        budget.fetch_budgeted_trading212_readonly(
            db_path=ledger, request_id="1"*32, account_scope_sha256=SCOPE,
            endpoint="instruments", account_type="INVEST", environment="DEMO",
            api_key="dummy", api_secret="dummy")
    assert calls == ["instruments"]
