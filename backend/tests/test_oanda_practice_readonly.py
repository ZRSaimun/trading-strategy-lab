"""Mock-only OANDA fxPractice read-only regression tests; zero network."""
from datetime import datetime, timezone, timedelta
import copy
import httpx
import pytest

from app.oanda_practice_readonly import OandaPracticeReadOnly

ACCOUNT = "101-001-1234567-001"
NOW = datetime(2026, 10, 26, 20, 12, 40, tzinfo=timezone.utc)


def account():
    return {"account": {"id": ACCOUNT, "currency": "GBP", "balance": "10000.00",
                        "NAV": "9990.00", "marginUsed": "0", "lastTransactionID": "42"},
            "lastTransactionID": "42"}


def prices():
    return {"prices": [{"instrument": "EUR_USD", "status": "tradeable",
                        "time": "2026-10-26T20:12:38.123456789Z",
                        "bids": [{"price": "1.09000", "liquidity": 100}],
                        "asks": [{"price": "1.09020", "liquidity": 100}]}]}


def adapter(response=None, *, enabled=True, status=200):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, json=response if response is not None else account())
    return OandaPracticeReadOnly(ACCOUNT, "test-token", enabled=enabled,
                                 transport=httpx.MockTransport(handler)), requests


def test_disabled_default_is_fail_closed():
    client, requests = adapter(enabled=False)
    with pytest.raises(PermissionError):
        client.account_summary()
    with pytest.raises(PermissionError):
        client.pricing(["EUR_USD"], as_of=NOW)
    assert not requests


def test_account_summary_is_get_only_practice_and_redacts_secret():
    client, requests = adapter()
    report = client.account_summary()
    assert report["NAV"] == "9990.00" and not report["may_execute_order"]
    assert "test-token" not in repr(client)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert str(requests[0].url) == "https://api-fxpractice.oanda.com/v3/accounts/" + ACCOUNT + "/summary"
    assert requests[0].headers["authorization"] == "Bearer test-token"


def test_pricing_fresh_bid_ask_and_no_execution():
    client, requests = adapter(prices())
    result = client.pricing(["EUR_USD"], as_of=NOW)
    assert result["prices"][0]["spread"] == "0.00020"
    assert not result["may_execute_real_order"] and not result["may_execute_demo_order"]
    assert requests[0].method == "GET"
    assert requests[0].url.params["instruments"] == "EUR_USD"


@pytest.mark.parametrize("mutate", [
    lambda x: x["account"].update(id="101-001-9999999-001"),
    lambda x: x.update(lastTransactionID="43"),
    lambda x: x["account"].update(currency="gbp"),
    lambda x: x["account"].update(balance="NaN"),
    lambda x: x["account"].update(NAV="-1"),
    lambda x: x["account"].update(marginUsed="1e2"),
    lambda x: x["account"].update(lastTransactionID="invalid"),
])
def test_invalid_account_evidence_fails_closed(mutate):
    body = account(); mutate(body)
    with pytest.raises(ValueError):
        adapter(body)[0].account_summary()


@pytest.mark.parametrize("mutate", [
    lambda x: x["prices"][0].update(status="non-tradeable"),
    lambda x: x["prices"][0].update(instrument="XAU_USD"),
    lambda x: x["prices"][0].update(time="2026-10-26T20:12:20Z"),
    lambda x: x["prices"][0].update(time="2026-10-26T20:12:41Z"),
    lambda x: x["prices"][0].update(time="bad"),
    lambda x: x["prices"][0]["bids"].clear(),
    lambda x: x["prices"][0]["asks"][0].update(price="1.08000"),
    lambda x: x["prices"][0]["bids"][0].update(price="NaN"),
    lambda x: x["prices"][0]["asks"][0].update(price="0"),
    lambda x: x["prices"].append(copy.deepcopy(x["prices"][0])),
])
def test_invalid_price_evidence_fails_closed(mutate):
    body = prices(); mutate(body)
    with pytest.raises(ValueError):
        adapter(body)[0].pricing(["EUR_USD"], as_of=NOW)


@pytest.mark.parametrize("bad", ["EUR/USD", "", "XAUUSD", "eur_usd", "../live", "EUR_USD?x=1"])
def test_instrument_injection_rejected_before_http(bad):
    client, requests = adapter(prices())
    with pytest.raises(ValueError):
        client.pricing([bad], as_of=NOW)
    assert not requests


@pytest.mark.parametrize("bad", [True, 1, -1, 61, 1.5])
def test_invalid_age_policy_rejected(bad):
    with pytest.raises(ValueError):
        adapter(prices())[0].pricing(["EUR_USD"], as_of=NOW, max_age_seconds=bad)


def test_missing_duplicate_instruments_and_naive_clock_rejected():
    client, requests = adapter(prices())
    for instruments, asof in [([], NOW), (["EUR_USD"] * 2, NOW),
                              (["EUR_USD"], NOW.replace(tzinfo=None))]:
        with pytest.raises(ValueError):
            client.pricing(instruments, as_of=asof)
    assert not requests


def test_http_failure_redirect_and_invalid_json_do_not_expose_token():
    for status in (301, 401, 429, 500):
        client, _ = adapter(status=status)
        with pytest.raises(ValueError) as e:
            client.account_summary()
        assert "test-token" not in str(e.value)
    client = OandaPracticeReadOnly(ACCOUNT, "test-token", enabled=True,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text="not json")))
    with pytest.raises(ValueError, match="Malformed"):
        client.account_summary()


def test_invalid_account_and_token_are_rejected():
    for account_id in ("", "../../accounts", "101-001-1234567-001?", ACCOUNT + "/orders"):
        with pytest.raises(ValueError):
            OandaPracticeReadOnly(account_id, "token", enabled=True)
    for token in ("", "token\r\nX: yes", "token with space", None):
        with pytest.raises(ValueError):
            OandaPracticeReadOnly(ACCOUNT, token, enabled=True)


def test_nanosecond_future_and_staleness_are_rejected_without_truncation():
    body = prices()
    body["prices"][0]["time"] = "2026-10-26T20:12:40.000000001Z"
    with pytest.raises(ValueError, match="Stale or future"):
        adapter(body)[0].pricing(["EUR_USD"], as_of=NOW)
    body["prices"][0]["time"] = "2026-10-26T20:12:34.999999999Z"
    with pytest.raises(ValueError, match="Stale or future"):
        adapter(body)[0].pricing(["EUR_USD"], as_of=NOW)


def test_practice_response_is_not_independent_broker_authentication():
    result = adapter()[0].account_summary()
    assert result["practice_api_response_validated"]
    assert result["independent_source_authentication_verified"] is False
