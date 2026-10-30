"""No-network synthetic broker equity metadata catalog regression tests."""
from copy import deepcopy
import pytest
from app.trading212_instrument_catalog import (
    InstrumentCatalogError, reconcile_trading212_instrument_catalog,
)

SHA = "a" * 64


def receipts():
    common = dict(provider="Trading 212", environment="DEMO", account_type_declared="INVEST",
                  account_type_verified=False, market_data_feed=False, cfd_supported=False,
                  may_execute_order=False, server_clock_attested=False, response_sha256=SHA,
                  received_at_utc="2026-10-26T19:30:00+00:00")
    a = dict(common, endpoint="instruments", data=[
        dict(ticker="AAPL_US_EQ", currencyCode="USD", type="STOCK",
             workingScheduleId=7, maxOpenQuantity=100.0, extendedHours=True,
             name="Apple Inc", shortName="Apple"),
        dict(ticker="SPY_US_EQ", currencyCode="USD", type="ETF",
             workingScheduleId=7, maxOpenQuantity=20, extendedHours=False,
             name="SPDR S&P 500", shortName="SPY"),
    ])
    b = dict(common, endpoint="exchanges", data=[
        dict(id=3, name="Example Exchange", workingSchedules=[dict(id=7, timeEvents=[])]),
    ])
    return a, b


def run(a=None, b=None, **kw):
    if a is None or b is None:
        original_a, original_b = receipts()
        a = original_a if a is None else a
        b = original_b if b is None else b
    return reconcile_trading212_instrument_catalog(
        a, b, declared_account_scope_sha256=SHA, **kw)


def test_valid_selected_equity_metadata_not_prices():
    a, b = receipts()
    result = run(a, b, requested_tickers=["AAPL_US_EQ", "NOT_LISTED"])
    assert result["status"] == "DECLARED_EQUITY_METADATA_RECONCILED_UNVERIFIED"
    assert result["instruments_count"] == 2 and result["exchanges_count"] == 1
    assert result["requested"][0]["ticker"] == "AAPL_US_EQ"
    assert result["not_found"] == ["NOT_LISTED"]
    assert result["instrument_types"] == {"ETF": 1, "STOCK": 1}
    assert len(result["catalog_sha256"]) == 64
    for key in ("same_account_verified", "provider_entitlement_verified", "market_calendar_verified",
                "metadata_freshness_verified", "market_data_feed", "price_freshness_verified",
                "cfd_supported", "may_execute_order"):
        assert result[key] is False
    assert "account_scope" not in str(result)


def test_order_independent_digest_and_no_unselected_tickers():
    a, b = receipts()
    original = run(a, b)
    a["data"].reverse()
    later = run(a, b)
    assert original["catalog_sha256"] == later["catalog_sha256"]
    assert later["requested"] == []


@pytest.mark.parametrize("mutator", [
    lambda a,b: a.update(endpoint="account_summary"),
    lambda a,b: a.update(account_type_verified=True),
    lambda a,b: a.update(market_data_feed=True),
    lambda a,b: b.update(cfd_supported=True),
    lambda a,b: b.update(environment="LIVE"),
    lambda a,b: b.update(account_type_declared="STOCKS_ISA"),
    lambda a,b: b.update(received_at_utc="2026-10-26T19:41:00Z"),
    lambda a,b: a.update(received_at_utc="2026-10-26T20:00:00+01:00"),
    lambda a,b: a.update(response_sha256="invalid"),
    lambda a,b: a["data"].append(deepcopy(a["data"][0])),
    lambda a,b: a["data"][0].update(workingScheduleId=4),
    lambda a,b: a["data"][0].update(maxOpenQuantity=float("nan")),
    lambda a,b: a["data"][0].update(type="CFD"),
    lambda a,b: a["data"][0].update(extendedHours=1),
    lambda a,b: a["data"][0].update(ticker="AAPL\nsecret"),
    lambda a,b: a["data"][0].update(currencyCode="usd"),
    lambda a,b: a["data"][0].update(name=""),
    lambda a,b: b["data"].append(deepcopy(b["data"][0])),
    lambda a,b: b["data"][0].update(id=True),
    lambda a,b: b["data"][0].update(workingSchedules=None),
    lambda a,b: a.update(data=[]),
    lambda a,b: b.update(data=[]),
])
def test_fail_closed_on_invalid_or_ambiguous_metadata(mutator):
    a,b=receipts()
    mutator(a,b)
    with pytest.raises(InstrumentCatalogError):
        run(a,b)


@pytest.mark.parametrize("selection", [["AAPL_US_EQ"] * 2, ["bad ticker"], ["A"] * 26, "AAPL_US_EQ", [1]])
def test_reject_ambiguous_selection(selection):
    with pytest.raises(InstrumentCatalogError):
        run(requested_tickers=selection)


def test_declared_scope_is_required_not_proof():
    a,b=receipts()
    with pytest.raises(InstrumentCatalogError):
        reconcile_trading212_instrument_catalog(a,b,declared_account_scope_sha256="bad")


def test_reject_oversized_populations():
    a,b=receipts()
    a["data"] *= 25001
    with pytest.raises(InstrumentCatalogError):
        run(a,b)


def test_catalog_digest_detects_schedule_or_quantity_drift():
    a,b=receipts()
    base=run(a,b)["catalog_sha256"]
    a["data"][0]["maxOpenQuantity"] = 101
    assert run(a,b)["catalog_sha256"] != base
    a,b=receipts()
    b["data"][0]["workingSchedules"][0]["timeEvents"] = [{"date": "2026-10-26T14:30:00Z", "type": "OPEN"}]
    assert run(a,b)["catalog_sha256"] != base


def test_catalog_digest_does_not_depend_on_exchange_order():
    a,b=receipts()
    b["data"].append(dict(id=5,name="Other Exchange",workingSchedules=[]))
    before=run(a,b)["catalog_sha256"]
    b["data"].reverse()
    assert run(a,b)["catalog_sha256"] == before

def test_working_schedule_joins_nested_schedule_not_exchange_id():
    a, b = receipts()
    selected = run(a, b, requested_tickers=["AAPL_US_EQ"])["requested"][0]
    assert selected["working_schedule_id"] == 7
    assert selected["exchange_id"] == 3
    assert selected["exchange_name"] == "Example Exchange"


@pytest.mark.parametrize("bad_schedules", [
    [], [dict(id=3, timeEvents=[])],
    [dict(id=7, timeEvents=[]), dict(id=7, timeEvents=[])],
    [dict(id=True, timeEvents=[])], [dict(id=-1, timeEvents=[])],
    [dict(id=7, timeEvents={})], ["not a schedule"],
    [dict(id=7, timeEvents=[])] * 1001,
])
def test_reject_missing_malformed_or_duplicate_working_schedule(bad_schedules):
    a, b = receipts()
    b["data"][0]["workingSchedules"] = bad_schedules
    with pytest.raises(InstrumentCatalogError):
        run(a, b)


def test_duplicate_schedule_id_across_exchanges_fails_closed():
    a, b = receipts()
    b["data"].append(dict(id=5, name="Other Exchange",
                          workingSchedules=[dict(id=7, timeEvents=[])]))
    with pytest.raises(InstrumentCatalogError):
        run(a, b)


def test_schedule_moved_to_other_exchange_changes_digest_and_link():
    a, b = receipts()
    previous = run(a, b)["catalog_sha256"]
    b["data"][0]["workingSchedules"] = []
    b["data"].append(dict(id=5, name="Other Exchange",
                          workingSchedules=[dict(id=7, timeEvents=[])]))
    current = run(a, b, requested_tickers=["AAPL_US_EQ"])
    assert current["catalog_sha256"] != previous
    assert current["requested"][0]["exchange_id"] == 5


def test_schedule_list_order_is_not_a_catalog_change():
    a, b = receipts()
    b["data"][0]["workingSchedules"].append(dict(id=8, timeEvents=[]))
    before = run(a, b)["catalog_sha256"]
    b["data"][0]["workingSchedules"].reverse()
    assert run(a, b)["catalog_sha256"] == before
