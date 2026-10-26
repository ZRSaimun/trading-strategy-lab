"""Synthetic offline tests: SQLite reservations never make paid provider requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio

import pytest

import app.provider_credit_budget as budget
import app.prospective_twelvedata_receipt as bridge
from app.expected_bar_manifest import compile_expected_m1_manifest

NOW = 1790000180
DAY = datetime.fromtimestamp(NOW, timezone.utc).date().isoformat()
HASH = "a" * 64
RIGHTS = "b" * 64


def ledger(tmp_path, monkeypatch, cap=2):
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW))
    path = str(tmp_path / "credit-budget.sqlite")
    budget.provision_daily_budget(
        path, utc_day=DAY, max_credits=cap,
        entitlement_evidence_sha256=HASH,
        rights_evidence_sha256=RIGHTS, owner_confirmed=True,
    )
    return path


def reserve(path, i):
    return budget.reserve_one_credit(
        path, request_id=f"{i:032x}", manifest_sha256=HASH,
    )


def test_no_implicit_file_creation_or_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW))
    path = str(tmp_path / "absent.sqlite")
    with pytest.raises(budget.CreditBudgetError):
        reserve(path, 1)
    assert not (tmp_path / "absent.sqlite").exists()


def test_provision_requires_exact_owner_approval(tmp_path):
    path = str(tmp_path / "credits.sqlite")
    for value in (False, 1, "true", None):
        with pytest.raises(budget.CreditBudgetError, match="owner"):
            budget.provision_daily_budget(
                path, utc_day=DAY, max_credits=2,
                entitlement_evidence_sha256=HASH,
                rights_evidence_sha256=RIGHTS, owner_confirmed=value,
            )
    assert not (tmp_path / "credits.sqlite").exists()


@pytest.mark.parametrize("cap", [True, 0, -1, 5001, 1.0, "3"])
def test_invalid_cap_rejected_without_creating_ledger(tmp_path, cap):
    path = str(tmp_path / "credits.sqlite")
    with pytest.raises(budget.CreditBudgetError):
        budget.provision_daily_budget(
            path, utc_day=DAY, max_credits=cap,
            entitlement_evidence_sha256=HASH,
            rights_evidence_sha256=RIGHTS, owner_confirmed=True,
        )
    assert not (tmp_path / "credits.sqlite").exists()


def test_consumes_credit_before_any_network_and_caps(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch)
    first = reserve(path, 1)
    second = reserve(path, 2)
    assert first["remaining_credits"] == 1
    assert second["remaining_credits"] == 0
    assert first["entitlement_verified"] is False
    assert second["rights_verified"] is False
    with pytest.raises(budget.CreditBudgetError, match="exhausted"):
        reserve(path, 3)


def test_request_replay_denied_without_refund(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch)
    reserve(path, 1)
    with pytest.raises(budget.CreditBudgetError):
        reserve(path, 1)
    assert reserve(path, 2)["remaining_credits"] == 0


def test_policy_is_immutable_after_first_provision(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch)
    with pytest.raises(budget.CreditBudgetError):
        budget.provision_daily_budget(
            path, utc_day=DAY, max_credits=5000,
            entitlement_evidence_sha256=HASH,
            rights_evidence_sha256=RIGHTS, owner_confirmed=True,
        )
    assert reserve(path, 1)["remaining_credits"] == 1
    assert reserve(path, 2)["remaining_credits"] == 0
    with pytest.raises(budget.CreditBudgetError):
        reserve(path, 3)


def test_new_day_requires_explicit_new_policy(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch)
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 86400))
    with pytest.raises(budget.CreditBudgetError, match="current UTC day"):
        reserve(path, 1)


def test_concurrent_reservations_never_exceed_cap(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch, cap=3)
    def attempt(i):
        try:
            return reserve(path, i)
        except budget.CreditBudgetError:
            return None
    with ThreadPoolExecutor(max_workers=8) as pool:
        outcomes = list(pool.map(attempt, range(1, 13)))
    accepted = [x for x in outcomes if x is not None]
    assert len(accepted) == 3
    assert sorted(x["remaining_credits"] for x in accepted) == [0, 1, 2]


@pytest.mark.parametrize("request_id, fingerprint", [
    ("not-hex", HASH), ("0"*32, "no"), (1, HASH), ("A"*32, HASH),
])
def test_invalid_reservation_identity_is_denied(tmp_path, monkeypatch, request_id, fingerprint):
    path = ledger(tmp_path, monkeypatch)
    with pytest.raises(budget.CreditBudgetError):
        budget.reserve_one_credit(path, request_id=request_id, manifest_sha256=fingerprint)
    assert reserve(path, 1)["remaining_credits"] == 1


def test_bridge_rejects_missing_budget_before_provider_call(monkeypatch):
    calls = []
    async def fake_provider(*args, **kwargs):
        calls.append(1)
        raise AssertionError("must not call provider")
    monkeypatch.setattr(bridge, "retrieve", fake_provider)
    monkeypatch.setattr(bridge, "_wall_clock", lambda: NOW)
    t = NOW - 180
    m = compile_expected_m1_manifest(
        provider="twelvedata", symbol="XAU/USD", venue="UNVERIFIED",
        price_side="UNSPECIFIED", calendar_id="synthetic",
        calendar_revision="r1", calendar_source="synthetic fixture",
        observed_at_utc=NOW, sessions_utc=[(t, t + 120)],
        exclusions_utc=[],
    )
    with pytest.raises(bridge.ProspectiveReceiptError, match="Durable"):
        asyncio.run(bridge.review_twelvedata_completed_m1(
            api_key="synthetic-key", manifest=m,
            owner_approved_api_credit_use=True,
            owner_asserted_data_rights=True,
        ))
    assert calls == []
