"""Synthetic offline tests: SQLite reservations never make paid provider requests."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio

import pytest

import app.provider_credit_budget as budget
import app.prospective_twelvedata_receipt as bridge
from app.expected_bar_manifest import compile_expected_m1_manifest

NOW = 1790000160
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
    assert first["remaining_credits"] == 1
    with pytest.raises(budget.CreditBudgetError, match="Per-minute"):
        reserve(path, 2)
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 60))
    second = reserve(path, 2)
    assert second["remaining_credits"] == 0
    assert first["entitlement_verified"] is False
    assert second["rights_verified"] is False
    with pytest.raises(budget.CreditBudgetError, match="exhausted"):
        reserve(path, 3)


def test_utc_minute_window_is_bounded_and_atomic(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch, cap=3)
    reserve(path, 1)
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 59))
    with pytest.raises(budget.CreditBudgetError, match="Per-minute"):
        reserve(path, 2)
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 60))
    assert reserve(path, 2)["remaining_credits"] == 1
    with pytest.raises(budget.CreditBudgetError, match="Per-minute"):
        reserve(path, 3)


def test_request_replay_denied_without_refund(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch)
    reserve(path, 1)
    with pytest.raises(budget.CreditBudgetError):
        reserve(path, 1)
    with pytest.raises(budget.CreditBudgetError, match="Per-minute"):
        reserve(path, 2)
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 60))
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
    with pytest.raises(budget.CreditBudgetError, match="Per-minute"):
        reserve(path, 2)
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 60))
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
    assert len(accepted) == 1
    assert accepted[0]["remaining_credits"] == 2
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 60))
    with ThreadPoolExecutor(max_workers=8) as pool:
        second = [x for x in pool.map(attempt, range(13, 25)) if x is not None]
    assert len(second) == 1
    assert second[0]["remaining_credits"] == 1
    monkeypatch.setattr(budget, "time", SimpleNamespace(time=lambda: NOW + 120))
    with ThreadPoolExecutor(max_workers=8) as pool:
        third = [x for x in pool.map(attempt, range(25, 37)) if x is not None]
    assert len(third) == 1
    assert third[0]["remaining_credits"] == 0


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


def test_bridge_reservation_is_not_refunded_after_provider_failure(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch, cap=1)
    monkeypatch.setattr(bridge, "_wall_clock", lambda: NOW)
    t = NOW - 180
    m = compile_expected_m1_manifest(
        provider="twelvedata", symbol="XAU/USD", venue="UNVERIFIED",
        price_side="UNSPECIFIED", calendar_id="synthetic",
        calendar_revision="r1", calendar_source="synthetic fixture",
        observed_at_utc=NOW, sessions_utc=[(t, t + 120)],
        exclusions_utc=[],
    )
    calls = []
    async def failed_provider(*args, **kwargs):
        calls.append(1)
        raise bridge.ProviderError("synthetic quota failure", 429)
    monkeypatch.setattr(bridge, "retrieve", failed_provider)

    def review(request_id):
        return asyncio.run(bridge.review_twelvedata_completed_m1(
            api_key="synthetic-key", manifest=m,
            owner_approved_api_credit_use=True,
            owner_asserted_data_rights=True,
            budget_db_path=path, budget_request_id=f"{request_id:032x}",
        ))

    with pytest.raises(bridge.ProspectiveReceiptError, match="Provider receipt rejected"):
        review(1)
    assert calls == [1]
    # Unknown vendor billing outcome cannot silently refund or retry.
    with pytest.raises(bridge.ProspectiveReceiptError, match="Durable"):
        review(2)
    assert calls == [1]


def test_new_ledger_has_private_mode(tmp_path, monkeypatch):
    import stat
    path = ledger(tmp_path, monkeypatch)
    assert stat.S_IMODE(__import__("os").stat(path).st_mode) == 0o600
    assert reserve(path, 1)["remaining_credits"] == 1


def test_group_readable_ledger_denied_before_reservation(tmp_path, monkeypatch):
    from pathlib import Path
    path = ledger(tmp_path, monkeypatch)
    Path(path).chmod(0o640)
    with pytest.raises(budget.CreditBudgetError, match="private"):
        reserve(path, 1)
    Path(path).chmod(0o600)
    assert reserve(path, 1)["remaining_credits"] == 1


def test_shared_ledger_directory_denied_before_reservation(tmp_path, monkeypatch):
    path = ledger(tmp_path, monkeypatch)
    tmp_path.chmod(0o755)
    try:
        with pytest.raises(budget.CreditBudgetError, match="private"):
            reserve(path, 1)
    finally:
        tmp_path.chmod(0o700)
    assert reserve(path, 1)["remaining_credits"] == 1


def test_hardlinked_ledger_denied_before_reservation(tmp_path, monkeypatch):
    import os
    path = ledger(tmp_path, monkeypatch)
    other = tmp_path / "other-ledger.sqlite"
    os.link(path, other)
    try:
        with pytest.raises(budget.CreditBudgetError, match="private"):
            reserve(path, 1)
    finally:
        other.unlink()
    assert reserve(path, 1)["remaining_credits"] == 1


def test_symlinked_ledger_denied_before_reservation(tmp_path, monkeypatch):
    from pathlib import Path
    path = ledger(tmp_path, monkeypatch)
    alias = tmp_path / "alias.sqlite"
    alias.symlink_to(Path(path))
    with pytest.raises(budget.CreditBudgetError):
        reserve(str(alias), 1)
    assert reserve(path, 1)["remaining_credits"] == 1


def test_provision_rejects_existing_public_file_without_mutation(tmp_path):
    path = tmp_path / "existing.sqlite"
    path.write_bytes(b"not a database")
    path.chmod(0o644)
    with pytest.raises(budget.CreditBudgetError, match="private"):
        budget.provision_daily_budget(
            str(path), utc_day=DAY, max_credits=1,
            entitlement_evidence_sha256=HASH,
            rights_evidence_sha256=RIGHTS, owner_confirmed=True,
        )
    assert path.read_bytes() == b"not a database"
