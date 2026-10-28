"""Synthetic-only quote consensus checks: no broker access or orders."""
from copy import deepcopy
import pytest
from app.paper_declared_quote_consensus import inspect_declared_quote_consensus

NOW = 1_800_000_000_000


def fixture():
    quotes = [
        dict(source="feed-A", instrument="XAUUSD", bid="99.90", ask="100.00", observed_at_ms=NOW-100, received_at_ms=NOW-50),
        dict(source="feed-B", instrument="XAUUSD", bid="99.91", ask="100.01", observed_at_ms=NOW-120, received_at_ms=NOW-70),
    ]
    limits = dict(max_quote_age_ms=1000, max_transport_lag_ms=500,
                  max_inter_source_skew_ms=500, max_mid_divergence_bps="20", max_spread_bps="20")
    return ["XAUUSD", "feed-A", quotes, limits, NOW]


def check(args):
    return inspect_declared_quote_consensus(*args)


def test_consensus_never_authorizes_execution():
    result = check(fixture())
    assert result["status"] == "DECLARED_QUOTE_CONSENSUS_UNVERIFIED"
    assert result["failed_checks"] == []
    assert result["source_count"] == 2
    for flag in ("quote_authenticated", "source_independence_verified", "broker_authenticated", "may_submit_paper_order", "may_submit_real_order"):
        assert result[flag] is False


@pytest.mark.parametrize("quote_index,key,value,reason", [
    (0, "instrument", "WTIUSD", "instrument_mismatch"),
    (0, "ask", "99.90", "crossed_or_locked_quote"),
    (0, "ask", "99.89", "crossed_or_locked_quote"),
    (0, "ask", "101", "spread_limit"),
    (0, "observed_at_ms", NOW-1001, "stale_or_future_quote"),
    (0, "observed_at_ms", NOW+1, "stale_or_future_quote"),
    (0, "received_at_ms", NOW+1, "stale_or_future_quote"),
    (0, "received_at_ms", NOW-900, "quote_transport_lag"),
    (0, "observed_at_ms", NOW-800, "inter_source_time_skew"),
    (1, "bid", "101", "mid_price_divergence"),
    (1, "source", "feed-A", "duplicate_quote_source"),
    (1, "bid", "100.005", "cross_source_market_inversion"),
])
def test_unsafe_quote_holds(quote_index, key, value, reason):
    args = fixture()
    args[2][quote_index][key] = value
    result = check(args)
    assert result["status"] == "HOLD_QUOTE_REVIEW"
    assert reason in result["failed_checks"]
    assert result["may_submit_real_order"] is False


def test_missing_primary_source_holds():
    args = fixture()
    args[1] = "feed-C"
    assert "missing_primary_source" in check(args)["failed_checks"]


@pytest.mark.parametrize("position,key,value", [
    (2, 0, None), (2, 0, "bad"), (2, 0, {}),
    (3, "max_quote_age_ms", True), (3, "max_transport_lag_ms", 0),
    (3, "max_inter_source_skew_ms", 60001),
    (3, "max_mid_divergence_bps", "0"), (3, "max_spread_bps", "10001"),
    (3, "max_spread_bps", "NaN"),
])
def test_invalid_schema_or_policy_rejected(position, key, value):
    args = fixture()
    args[position][key] = value
    with pytest.raises(ValueError):
        check(args)


@pytest.mark.parametrize("value", [[], [fixture()[2][0]], fixture()[2]*3, "bad", None])
def test_quote_population_rejected(value):
    args = fixture()
    args[2] = value
    with pytest.raises(ValueError):
        check(args)


def test_extra_fields_rejected():
    args = fixture()
    args[2][0]["is_trusted"] = True
    with pytest.raises(ValueError):
        check(args)


def test_immutable_inputs():
    args = fixture()
    before = deepcopy(args)
    check(args)
    assert args == before


def test_exact_age_and_skew_boundaries():
    args = fixture()
    args[2][0].update(observed_at_ms=NOW-1000, received_at_ms=NOW-500)
    args[2][1].update(observed_at_ms=NOW-500, received_at_ms=NOW-100)
    assert check(args)["failed_checks"] == []


def test_below_mid_divergence_boundary():
    args = fixture()
    args[3]["max_mid_divergence_bps"] = "2"
    assert check(args)["failed_checks"] == []


def test_quote_numeric_types_rejected():
    args = fixture()
    args[2][0]["bid"] = 99.9
    with pytest.raises(ValueError):
        check(args)


def test_unsupported_time_type_rejected():
    args = fixture()
    args[4] = True
    with pytest.raises(ValueError):
        check(args)
