"""Synthetic, offline, no-network OANDA practice idrange tests."""
from datetime import datetime, timezone
import copy
import pytest

from app.oanda_practice_transaction_range import (
    read_practice_transaction_range, validate_practice_transaction_range,
)

ACCOUNT = "101-001-1234567-001"
NOW = datetime(2026, 10, 26, 20, 12, 40, tzinfo=timezone.utc)


def event(number, **overrides):
    row = {"id": str(number), "accountID": ACCOUNT, "type": "ORDER_FILL",
           "time": "2026-10-26T20:12:39.123456789Z", "instrument": "EUR_USD"}
    row.update(overrides)
    return row


def body(*ids, cursor="45"):
    return {"transactions": [event(i) for i in ids], "lastTransactionID": cursor}


def check(response, first="41", last="43", **kw):
    return validate_practice_transaction_range(response, account_id=ACCOUNT,
                                               first_id=first, last_id=last,
                                               as_of=kw.get("as_of", NOW))


def test_complete_bounded_range_is_not_authentication_or_trade_permission():
    result = check(body(41, 42, 43))
    assert result["observed_contiguous_id_range"] is True
    assert result["missing_id_count"] == 0
    assert result["observed_type_counts"] == {"ORDER_FILL": 3}
    assert not result["complete_broker_history_authenticated"]
    assert not result["original_response_bytes_authenticated"]
    assert not result["cash_ledger_reconciled"]
    assert not result["may_execute_real_order"] and not result["may_execute_demo_order"]
    assert len(result["canonical_response_sha256"]) == 64
    assert "instrument" not in str(result)


def test_gaps_and_empty_responses_do_not_claim_completeness():
    missing = check(body(41, 43))
    assert missing["missing_id_count"] == 1 and not missing["observed_contiguous_id_range"]
    empty = check(body())
    assert empty["missing_id_count"] == 3 and empty["observed_count"] == 0


def test_singleton_and_maximum_allowed_range():
    assert check(body(1, cursor="1"), first="1", last="1")["observed_count"] == 1
    many = check(body(*range(1, 101), cursor="100"), first="1", last="100")
    assert many["observed_count"] == 100 and many["missing_id_count"] == 0


@pytest.mark.parametrize("first,last", [
    ("0", "1"), ("1", "101"), ("44", "43"), ("01", "2"), ("-1", "1"),
    ("1", "1e2"), ("1", "1/../orders"), ("1", "1?x=y"), ("1", 1),
    (True, "1"), ("999999999999999999999", "999999999999999999999"),
])
def test_invalid_range_fails_before_any_get(first, last):
    client = Fake(body(41, 42, 43))
    with pytest.raises(ValueError):
        read_practice_transaction_range(client, first, last, as_of=NOW)
    assert client.requests == []


@pytest.mark.parametrize("mutation", [
    lambda x: x.update(lastTransactionID="42"),
    lambda x: x.update(lastTransactionID="04"),
    lambda x: x.update(transactions="invalid"),
    lambda x: x.update(transactions=[event(41), event(41)]),
    lambda x: x.update(transactions=[event(42), event(41)]),
    lambda x: x.update(transactions=[event(41), event(44)]),
    lambda x: x.update(transactions=[event(41, accountID="101-001-9999999-001")]),
    lambda x: x.update(transactions=[event(41, accountID=None)]),
    lambda x: x.update(transactions=[event(41, id=41)]),
    lambda x: x.update(transactions=[event(41, type="order_fill")]),
    lambda x: x.update(transactions=[event(41, time="2026-10-26T20:12:40.000000001Z")]),
    lambda x: x.update(transactions=[event(41, time="2026-10-26T20:12:41Z")]),
    lambda x: x.update(transactions=[event(41, time="not-a-time")]),
    lambda x: x.update(transactions=[event(41, time="2026-02-30T20:12:39Z")]),
    lambda x: x.update(transactions=[event(41, time="2026-10-26T20:12:39Z"),
                                       event(42, time="2026-10-26T20:12:38Z")]),
    lambda x: x.update(unexpected=True),
])
def test_invalid_native_responses_fail_closed(mutation):
    payload = body(41, 42, 43)
    mutation(payload)
    with pytest.raises(ValueError):
        check(payload)


class Fake:
    _account = ACCOUNT
    def __init__(self, payload, enabled=True):
        self.payload = payload
        self.enabled = enabled
        self.requests = []

    def _get(self, path, params):
        if not self.enabled:
            raise PermissionError("Disabled")
        self.requests.append((path, params))
        return copy.deepcopy(self.payload)


def test_only_allowlisted_idrange_get_path_is_used():
    client = Fake(body(41, 42, 43))
    result = read_practice_transaction_range(client, "41", "43", as_of=NOW)
    assert result["observed_count"] == 3
    assert client.requests == [("/transactions/idrange", {"from": "41", "to": "43"})]


def test_disabled_adapter_fails_closed_without_request():
    client = Fake(body(41), enabled=False)
    with pytest.raises(PermissionError):
        read_practice_transaction_range(client, "41", "43", as_of=NOW)
    assert client.requests == []


def test_naive_cutoff_fails_before_get():
    client = Fake(body(41))
    with pytest.raises(ValueError):
        read_practice_transaction_range(client, "41", "43", as_of=NOW.replace(tzinfo=None))
    assert client.requests == []


def test_digest_stable_for_key_order_but_not_a_broker_signature():
    p = body(41, 42, 43)
    q = {"lastTransactionID": p["lastTransactionID"], "transactions": p["transactions"]}
    assert check(p)["canonical_response_sha256"] == check(q)["canonical_response_sha256"]
    altered = copy.deepcopy(p)
    altered["transactions"][0]["instrument"] = "XAU_USD"
    assert check(altered)["canonical_response_sha256"] != check(p)["canonical_response_sha256"]


def test_actual_practice_adapter_uses_mocked_get_only_and_never_orders():
    # This integration test runs in repository CI with the companion draft PR.
    # The local standalone validation suite may not contain that adapter.
    httpx = pytest.importorskip("httpx")
    module = pytest.importorskip("app.oanda_practice_readonly")
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=body(41, 42, 43))
    client = module.OandaPracticeReadOnly(ACCOUNT, "mock-secret", enabled=True,
                                          transport=httpx.MockTransport(handler))
    report = read_practice_transaction_range(client, "41", "43", as_of=NOW)
    assert report["observed_count"] == 3 and not report["may_execute_real_order"]
    assert len(requests) == 1 and requests[0].method == "GET"
    assert requests[0].url.host == "api-fxpractice.oanda.com"
    assert requests[0].url.path == "/v3/accounts/" + ACCOUNT + "/transactions/idrange"
    assert requests[0].url.params["from"] == "41"
    assert requests[0].url.params["to"] == "43"
    assert "mock-secret" not in str(report)


def test_actual_adapter_disabled_by_default_blocks_transaction_read():
    module = pytest.importorskip("app.oanda_practice_readonly")
    client = module.OandaPracticeReadOnly(ACCOUNT, "mock-secret")
    with pytest.raises(PermissionError):
        read_practice_transaction_range(client, "41", "43", as_of=NOW)


def test_non_json_nested_evidence_rejected():
    response = body(41)
    response["transactions"][0]["bad"] = float("nan")
    with pytest.raises(ValueError, match="Non-JSON"):
        check(response)
