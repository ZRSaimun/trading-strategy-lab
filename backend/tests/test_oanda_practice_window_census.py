"""Synthetic only: no network, no broker access, no executable orders."""
import copy
from datetime import datetime, timezone
import random

import pytest

from app.oanda_practice_window_census import (
    audit_practice_transaction_windows,
    inspect_practice_transaction_windows,
    plan_practice_transaction_windows,
)

ACCOUNT = "101-001-1234567-001"
NOW = datetime(2026, 10, 26, 22, 10, tzinfo=timezone.utc)


def report(start, end, *, ids=None, cursor="205"):
    ids = list(range(int(start), int(end) + 1)) if ids is None else ids
    return {
        "provider": "OANDA_V20_PRACTICE", "account_id": ACCOUNT,
        "requested_first_id": str(start), "requested_last_id": str(end),
        "broker_reported_latest_id": cursor,
        "observed_ids": [str(n) for n in ids], "observed_count": len(ids),
        "missing_id_count": int(end) - int(start) + 1 - len(ids),
        "observed_contiguous_id_range": len(ids) == int(end) - int(start) + 1,
        "observed_type_counts": {"ORDER_FILL": len(ids)} if ids else {},
        "canonical_response_sha256": "a" * 64,
        "original_response_bytes_authenticated": False,
        "complete_broker_history_authenticated": False,
        "cash_ledger_reconciled": False,
        "may_execute_demo_order": False, "may_execute_real_order": False,
    }


def audit(rows, first="1", last="205", cursor="205", **kw):
    return audit_practice_transaction_windows(
        rows, account_id=ACCOUNT, first_id=first, last_id=last,
        snapshot_last_id=cursor, **kw,
    )


def test_complete_three_window_census_is_not_broker_authentication():
    rows = [report(1, 100), report(101, 200), report(201, 205)]
    result = audit(rows)
    assert result["window_count"] == 3
    assert result["observed_count"] == 205
    assert result["missing_declared_id_count"] == 0
    assert result["declared_window_status"] == "NO_GAPS_IN_DECLARED_RANGES"
    assert result["observed_type_counts"] == {"ORDER_FILL": 205}
    assert result["complete_broker_history_authenticated"] is False
    assert result["cash_ledger_reconciled"] is False
    assert result["may_execute_real_order"] is False
    assert result["may_execute_demo_order"] is False


def test_missing_ids_reported_without_false_completeness():
    rows = [report(1, 100, ids=[i for i in range(1, 101) if i != 50]),
            report(101, 200, ids=[i for i in range(101, 201) if i != 105]),
            report(201, 205, ids=[201, 202, 203, 204])]
    result = audit(rows)
    assert result["observed_count"] == 202
    assert result["missing_declared_id_count"] == 3
    assert result["missing_declared_id_sample"] == ["50", "105", "205"]
    assert result["declared_window_status"] == "MISSING_IDS_IN_DECLARED_RANGES"


def test_empty_windows_report_bounded_gap_sample():
    rows = [report(1, 100, ids=[]), report(101, 200, ids=[]),
            report(201, 205, ids=[])]
    result = audit(rows)
    assert result["observed_count"] == 0
    assert result["missing_declared_id_count"] == 205
    assert result["missing_declared_id_sample"] == [str(i) for i in range(1, 21)]


def test_maximum_2000_id_partition_and_2001_rejected():
    windows = plan_practice_transaction_windows("1", "2000")
    assert len(windows) == 20 and windows[-1] == ("1901", "2000")
    rows = [report(a, b, cursor="2000") for a, b in windows]
    assert audit(rows, first="1", last="2000", cursor="2000")["observed_count"] == 2000
    with pytest.raises(ValueError, match="Unbounded"):
        plan_practice_transaction_windows("1", "2001")


@pytest.mark.parametrize("first,last", [
    ("0", "1"), ("01", "1"), ("1", "0"), ("2", "1"),
    ("1", "2001"), ("1", "999999999999999999999"),
    ("-1", "2"), ("1e2", "200"), (True, "2"), (1, "2"),
])
def test_invalid_window_plans_fail_closed(first, last):
    with pytest.raises(ValueError):
        plan_practice_transaction_windows(first, last)


@pytest.mark.parametrize("mutation", [
    lambda r: r.update(account_id="101-001-7654321-001"),
    lambda r: r.update(provider="OANDA_LIVE"),
    lambda r: r.update(requested_first_id="2"),
    lambda r: r.update(requested_last_id="99"),
    lambda r: r.update(broker_reported_latest_id="206"),
    lambda r: r.update(broker_reported_latest_id="0205"),
    lambda r: r.update(observed_ids=["1", "1"]),
    lambda r: r.update(observed_ids=["2", "1"]),
    lambda r: r.update(observed_ids=["0"]),
    lambda r: r.update(observed_ids=["101"]),
    lambda r: r.update(observed_ids=[1]),
    lambda r: r.update(observed_count=True),
    lambda r: r.update(observed_count=99),
    lambda r: r.update(missing_id_count=-1),
    lambda r: r.update(observed_contiguous_id_range="true"),
    lambda r: r.update(observed_contiguous_id_range=False),
    lambda r: r.update(observed_type_counts={"ORDER_FILL": 99}),
    lambda r: r.update(observed_type_counts={"ORDER_FILL": True}),
    lambda r: r.update(observed_type_counts={"order_fill": 100}),
    lambda r: r.update(canonical_response_sha256="not-a-sha"),
    lambda r: r.update(complete_broker_history_authenticated=True),
    lambda r: r.update(may_execute_demo_order=True),
    lambda r: r.update(cash_ledger_reconciled=True),
    lambda r: r.update(extra_field="surprise"),
])
def test_tampered_report_fails_closed(mutation):
    rows = [report(1, 100), report(101, 200), report(201, 205)]
    mutation(rows[0])
    with pytest.raises(ValueError):
        audit(rows)


def test_missing_reordered_and_duplicated_windows_rejected():
    rows = [report(1, 100), report(101, 200), report(201, 205)]
    for bad in (rows[:-1], rows + [rows[-1]], rows[::-1],
                [rows[0], rows[0], rows[2]]):
        with pytest.raises(ValueError):
            audit(bad)


def test_fingerprint_stable_across_mapping_order_and_frozen_change_rejected():
    rows = [report(1, 100), report(101, 200), report(201, 205)]
    baseline = audit(rows)
    assert audit([dict(reversed(list(row.items()))) for row in rows])[
        "census_sha256"] == baseline["census_sha256"]
    assert audit(rows, expected_census_sha256=baseline["census_sha256"])[
        "census_sha256"] == baseline["census_sha256"]
    changed = copy.deepcopy(rows)
    changed[1]["canonical_response_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="externally frozen"):
        audit(changed, expected_census_sha256=baseline["census_sha256"])
    assert audit(changed)["census_sha256"] != baseline["census_sha256"]


def test_randomized_bounded_population_census():
    rng = random.Random(20261026)
    for _ in range(250):
        size = rng.randint(1, 2000)
        windows = plan_practice_transaction_windows("1", str(size))
        rows = []
        expected_missing = 0
        for start, end in windows:
            ids = [i for i in range(int(start), int(end) + 1) if rng.random() >= 0.08]
            expected_missing += int(end) - int(start) + 1 - len(ids)
            rows.append(report(start, end, ids=ids, cursor=str(size)))
        result = audit(rows, last=str(size), cursor=str(size))
        assert result["observed_count"] + result["missing_declared_id_count"] == size
        assert result["missing_declared_id_count"] == expected_missing
        assert len(result["missing_declared_id_sample"]) <= 20


def test_wrapper_budget_rejected_before_any_possible_get():
    class Client:
        _account = ACCOUNT
    client = Client()
    with pytest.raises(ValueError, match="budget"):
        inspect_practice_transaction_windows(
            client, "1", "205", as_of=NOW, snapshot_last_id="205",
            max_requests=2,
        )
    with pytest.raises(ValueError, match="cutoff"):
        inspect_practice_transaction_windows(
            client, "1", "205", as_of=NOW.replace(tzinfo=None),
            snapshot_last_id="205",
        )


def test_real_companion_fake_get_only_and_cursor_drift_abort():
    pytest.importorskip("app.oanda_practice_transaction_range")
    class Fake:
        _account = ACCOUNT
        def __init__(self, drift=False):
            self.requests = []
            self.drift = drift
        def _get(self, path, params):
            self.requests.append((path, dict(params)))
            first, last = int(params["from"]), int(params["to"])
            cursor = "206" if self.drift and first > 100 else "205"
            return {"transactions": [
                {"id": str(i), "accountID": ACCOUNT, "type": "ORDER_FILL",
                 "time": "2026-10-26T22:09:00Z"}
                for i in range(first, last + 1)
            ], "lastTransactionID": cursor}
    client = Fake()
    result = inspect_practice_transaction_windows(
        client, "1", "205", as_of=NOW, snapshot_last_id="205",
    )
    assert result["observed_count"] == 205
    assert len(client.requests) == 3
    assert all(path == "/transactions/idrange" for path, _ in client.requests)
    assert client.requests[0][1] == {"from": "1", "to": "100"}
    drift = Fake(drift=True)
    with pytest.raises(ValueError, match="cursor drift"):
        inspect_practice_transaction_windows(
            drift, "1", "205", as_of=NOW, snapshot_last_id="205",
        )
    assert len(drift.requests) == 2  # stop before the third GET
