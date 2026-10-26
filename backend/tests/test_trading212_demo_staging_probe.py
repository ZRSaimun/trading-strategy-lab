"""Synthetic-only owner-invoked staging probe tests. No broker connections."""
from copy import deepcopy
import json

import pytest
from app import trading212_demo_staging_probe as probe
from app import trading212_request_budget as budget


def receipt(**changes):
    base = {
        "provider": "Trading 212", "endpoint": "instruments",
        "environment": "DEMO", "account_type_declared": "INVEST",
        "account_type_verified": False, "server_clock_attested": False,
        "market_data_feed": False, "price_freshness_verified": False,
        "cfd_supported": False, "may_execute_order": False,
        "response_sha256": "a" * 64,
        "received_at_utc": "2026-10-26T21:00:00+00:00",
        "data": [{"ticker": "PRIVATE"}],
        "rate_limit_observation": {
            "status": "OBSERVED_UNVERIFIED", "account_quota_verified": False,
            "safe_to_make_another_request": False,
        },
    }
    base.update(changes)
    return base


def args(**changes):
    base = dict(owner_confirmed=True, db_path="/private/ledger",
                request_id="1" * 32, account_scope_sha256="b" * 64,
                endpoint="instruments", account_type="INVEST",
                api_key="private-key", api_secret="private-secret")
    base.update(changes)
    return base


def test_explicit_opt_in_and_no_order_or_live_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr(budget, "fetch_budgeted_trading212_readonly", lambda **kw: calls.append(kw))
    for changes in ({"owner_confirmed": False}, {"owner_confirmed": 1},
                    {"endpoint": "account_summary"}, {"endpoint": "orders"},
                    {"endpoint": []}, {"account_type": "CFD"},
                    {"request_id": "bad"}):
        with pytest.raises(probe.DemoStagingProbeError):
            probe.probe_trading212_demo_metadata(**args(**changes))
    assert calls == []


def test_redacted_bound_result(monkeypatch):
    calls = []
    def fake(**kw):
        calls.append(kw)
        return receipt()
    monkeypatch.setattr(budget, "fetch_budgeted_trading212_readonly", fake)
    out = probe.probe_trading212_demo_metadata(**args())
    assert len(calls) == 1 and calls[0]["environment"] == "DEMO"
    assert calls[0]["endpoint"] == "instruments"
    assert out["status"] == "DEMO_METADATA_OBSERVED_UNVERIFIED"
    assert out["declared_items_count"] == 1
    assert out["request_id_sha256"] != "1" * 32
    assert all(out[k] is False for k in ("may_execute_order", "cfd_supported",
                 "data_rights_verified", "market_data_feed"))
    serialized = json.dumps(out)
    for private in ("PRIVATE", "private-key", "private-secret", "/private/ledger", "b" * 64):
        assert private not in serialized


@pytest.mark.parametrize("changes", [
    {"provider": "unknown"}, {"endpoint": "exchanges"},
    {"environment": "LIVE"}, {"account_type_declared": "CFD"},
    {"market_data_feed": True}, {"may_execute_order": True},
    {"account_type_verified": True}, {"server_clock_attested": True},
    {"response_sha256": "bad"}, {"received_at_utc": "2026-10-26"},
    {"received_at_utc": "2026-10-26T21:00:00+01:00"},
    {"data": {}}, {"data": [0] * 50001},
    {"rate_limit_observation": {"status": "OBSERVED_UNVERIFIED", "account_quota_verified": True, "safe_to_make_another_request": False}},
    {"rate_limit_observation": {"status": [], "account_quota_verified": False, "safe_to_make_another_request": False}},
    {"rate_limit_observation": {"status": "BAD", "account_quota_verified": False, "safe_to_make_another_request": False}},
])
def test_invalid_or_overstated_receipts_rejected(changes):
    with pytest.raises(probe.DemoStagingProbeError):
        probe._validate_receipt(receipt(**changes), endpoint="instruments", account_type="INVEST")


def test_empty_or_missing_quota_is_review_not_verified():
    for data, status in (([], "OBSERVED_UNVERIFIED"), ([{"ticker": "X"}], "MISSING_REVIEW_REQUIRED")):
        r = receipt(data=data)
        r["rate_limit_observation"]["status"] = status
        out = probe._validate_receipt(r, endpoint="instruments", account_type="INVEST")
        assert out["status"] == "REVIEW_REQUIRED"


def test_broker_error_does_not_trigger_retry(monkeypatch):
    calls = []
    def fake(**kw):
        calls.append(kw)
        raise budget.BrokerBudgetError("Read reservation denied")
    monkeypatch.setattr(budget, "fetch_budgeted_trading212_readonly", fake)
    with pytest.raises(budget.BrokerBudgetError):
        probe.probe_trading212_demo_metadata(**args())
    assert len(calls) == 1


def test_input_receipt_not_mutated():
    r = receipt()
    original = deepcopy(r)
    probe._validate_receipt(r, endpoint="instruments", account_type="INVEST")
    assert r == original
