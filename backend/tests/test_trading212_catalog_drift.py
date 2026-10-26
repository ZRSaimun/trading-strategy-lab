"""No-network synthetic Trading 212 declared equity catalog drift tests."""
from copy import deepcopy

import pytest

from app.trading212_catalog_drift import compare_trading212_catalogs
from app.trading212_instrument_catalog import InstrumentCatalogError

SHA = "a" * 64


def _receipts(at="2026-10-26T19:30:00Z"):
    common = {
        "provider": "Trading 212", "environment": "DEMO",
        "account_type_declared": "INVEST", "account_type_verified": False,
        "market_data_feed": False, "cfd_supported": False,
        "may_execute_order": False, "server_clock_attested": False,
        "response_sha256": SHA, "received_at_utc": at,
    }
    instruments = {
        **common, "endpoint": "instruments",
        "data": [
            {
                "ticker": "AAPL_US_EQ", "currencyCode": "USD", "type": "STOCK",
                "workingScheduleId": 3, "maxOpenQuantity": 100,
                "extendedHours": True, "name": "Apple Inc", "shortName": "Apple",
            },
            {
                "ticker": "SPY_US_EQ", "currencyCode": "USD", "type": "ETF",
                "workingScheduleId": 3, "maxOpenQuantity": 20,
                "extendedHours": False, "name": "SPDR S&P 500", "shortName": "SPY",
            },
        ],
    }
    exchanges = {
        **common, "endpoint": "exchanges",
        "data": [{"id": 3, "name": "Synthetic Exchange", "workingSchedules": []}],
    }
    return instruments, exchanges


def _pair():
    return (*_receipts(), *_receipts("2026-10-26T19:50:00Z"))


def _compare(pair=None, **kwargs):
    if pair is None:
        pair = _pair()
    return compare_trading212_catalogs(
        *pair, declared_account_scope_sha256=SHA, **kwargs,
    )


def test_identical_declared_catalog_is_not_live_or_verified():
    report = _compare(requested_tickers=["AAPL_US_EQ", "UNKNOWN"])
    assert report["review"] == "NO_DECLARED_CHANGE_OBSERVED"
    assert report["shared_instruments_count"] == 2
    assert report["added_instruments_count"] == 0
    assert report["removed_instruments_count"] == 0
    assert report["changed_shared_instruments_count"] == 0
    assert report["catalog_digest_changed"] is False
    assert [r["change"] for r in report["requested"]] == [
        "NO_DECLARED_METADATA_CHANGE", "ABSENT_IN_BOTH",
    ]
    for field in ("same_account_verified", "provider_entitlement_verified",
                  "source_authenticity_verified", "market_calendar_verified",
                  "market_data_feed", "cfd_supported", "may_execute_order"):
        assert report[field] is False
    assert SHA not in str(report)
    assert "api_key" not in str(report)


def test_detects_quantity_and_type_changes_without_full_ticker_dump():
    pair = _pair()
    pair[2]["data"][0]["maxOpenQuantity"] = 101
    pair[2]["data"][1]["type"] = "STOCK"
    report = _compare(pair, requested_tickers=["AAPL_US_EQ"])
    assert report["review"] == "REVIEW_REQUIRED"
    assert report["changed_shared_instruments_count"] == 2
    assert report["changed_field_counts"]["max_open_quantity"] == 1
    assert report["changed_field_counts"]["type"] == 1
    assert report["requested"][0]["change"] == "DECLARED_METADATA_CHANGED"
    assert "SPY_US_EQ" not in str(report)


def test_detects_added_and_removed_as_declared_population_only():
    pair = _pair()
    pair[2]["data"].pop(0)
    pair[2]["data"].append({
        "ticker": "MSFT_US_EQ", "currencyCode": "USD", "type": "STOCK",
        "workingScheduleId": 3, "maxOpenQuantity": 50,
        "extendedHours": False, "name": "Microsoft", "shortName": "MSFT",
    })
    report = _compare(pair, requested_tickers=["AAPL_US_EQ", "MSFT_US_EQ"])
    assert report["added_instruments_count"] == 1
    assert report["removed_instruments_count"] == 1
    assert report["shared_instruments_count"] == 1
    assert [r["change"] for r in report["requested"]] == [
        "REMOVED_FROM_DECLARED_CATALOG", "ADDED_TO_DECLARED_CATALOG",
    ]


def test_exchange_schedule_change_triggers_review_even_with_unchanged_tickers():
    pair = _pair()
    pair[3]["data"][0]["workingSchedules"] = [{"dayOfWeek": "MONDAY"}]
    report = _compare(pair)
    assert report["changed_shared_instruments_count"] == 0
    assert report["catalog_digest_changed"] is True
    assert report["review"] == "REVIEW_REQUIRED"


def test_instrument_order_does_not_trigger_false_drift():
    pair = _pair()
    pair[2]["data"].reverse()
    assert _compare(pair)["review"] == "NO_DECLARED_CHANGE_OBSERVED"


@pytest.mark.parametrize("mutate", [
    lambda p: p[2].update(received_at_utc="2026-10-26T19:30:00Z"),
    lambda p: p[2].update(received_at_utc="2026-10-26T19:20:00Z"),
    lambda p: p[2].update(received_at_utc="2026-10-26T19:40:00Z"),
    lambda p: p[2].update(environment="LIVE"),
    lambda p: p[3].update(account_type_declared="STOCKS_ISA"),
    lambda p: p[0].update(market_data_feed=True),
    lambda p: p[2]["data"][0].update(type="CFD"),
    lambda p: p[3]["data"][0].update(workingSchedules=None),
])
def test_invalid_or_ambiguous_catalogs_fail_closed(mutate):
    pair = _pair()
    mutate(pair)
    with pytest.raises(InstrumentCatalogError):
        _compare(pair)


@pytest.mark.parametrize("tickers", [
    "AAPL_US_EQ", ["AAPL_US_EQ"] * 2, ["BAD TICKER"],
    ["A"] * 26, [True],
])
def test_unbounded_or_invalid_selection_rejected(tickers):
    with pytest.raises(InstrumentCatalogError):
        _compare(requested_tickers=tickers)


def test_malformed_scope_rejected():
    with pytest.raises(InstrumentCatalogError):
        compare_trading212_catalogs(*_pair(), declared_account_scope_sha256="bad")


def test_pair_is_not_mutated():
    pair = _pair()
    before = deepcopy(pair)
    _compare(pair, requested_tickers=["AAPL_US_EQ"])
    assert pair == before
