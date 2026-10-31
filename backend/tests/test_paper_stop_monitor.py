"""Synthetic, disconnected paper stop quote safety regressions."""
from dataclasses import replace
import pytest
from app.paper_stop_monitor import PaperQuote, PaperStop, QuotePolicy, observe_paper_stop

NOW = 1_790_000_000_000
STOP = PaperStop(position_id="paper-position-001", instrument="XAUUSD", provider="DEMO-TEST",
                 venue="TEST-OTC", side="LONG", entry_price="100", protective_stop="99",
                 quantity="2", point_value_cash="10", assumed_exit_cost_cash="1.25")
QUOTE = PaperQuote(instrument="XAUUSD", provider="DEMO-TEST", venue="TEST-OTC",
                   quote_id="quote-000001", sequence=20, bid="99.50", ask="99.52",
                   observed_at_ms=NOW - 400, received_at_ms=NOW - 300)
POLICY = QuotePolicy(max_quote_age_ms=1000, max_transport_lag_ms=500, max_spread_bps="10",
                     previous_sequence=19, previous_observed_at_ms=NOW - 500,
                     previous_quote_id="quote-000000")


def run(stop=STOP, quote=QUOTE, policy=POLICY, now=NOW):
    return observe_paper_stop(stop, quote, policy, server_now_ms=now)


def test_no_breach_never_executes():
    result = run()
    assert result["structural_checks_pass"] and not result["stop_breach_observed"]
    assert result["candidate_exit_price"] is None
    assert not result["quote_authenticated"] and not result["may_execute_real_order"]
    assert not result["may_execute_paper_order"] and not result["paper_fill_recorded"]


def test_long_bid_stop_gap_is_not_assumed_fill_at_stop():
    result = run(quote=replace(QUOTE, bid="98.50", ask="98.52"))
    assert result["stop_breach_observed"] and result["adverse_stop_gap"]
    assert result["candidate_exit_side"] == "BID"
    assert result["candidate_exit_price"] == "98.50"
    assert result["candidate_pnl_cash_before_unmodeled_fees"] == "-31.25"
    assert result["requires_human_reconciliation"]
    assert not result["broker_stop_accepted"]


def test_long_at_stop_boundary():
    result = run(quote=replace(QUOTE, bid="99", ask="99.02"))
    assert result["stop_breach_observed"] and not result["adverse_stop_gap"]


def test_short_uses_ask_not_bid():
    short = replace(STOP, side="SHORT", entry_price="100", protective_stop="101")
    result = run(stop=short, quote=replace(QUOTE, bid="100.99", ask="101.01"))
    assert result["stop_breach_observed"] and result["adverse_stop_gap"]
    assert result["candidate_exit_side"] == "ASK"
    assert result["candidate_pnl_cash_before_unmodeled_fees"] == "-21.45"
    assert not run(stop=short, quote=replace(QUOTE, bid="100.97", ask="100.99"))["stop_breach_observed"]


@pytest.mark.parametrize("change,check", [
    ({"instrument": "US100"}, "exact_source_identity"),
    ({"provider": "OTHER"}, "exact_source_identity"),
    ({"venue": "OTHER"}, "exact_source_identity"),
    ({"bid": "100", "ask": "99"}, "valid_bid_ask"),
    ({"bid": "100", "ask": "100"}, "valid_bid_ask"),
    ({"bid": "98", "ask": "99"}, "spread_within_limit"),
    ({"observed_at_ms": NOW - 1500}, "fresh_quote"),
    ({"received_at_ms": NOW + 1}, "timestamp_order"),
    ({"received_at_ms": NOW - 1, "observed_at_ms": NOW - 1000}, "transport_lag"),
    ({"sequence": 19}, "sequence_increases"),
    ({"observed_at_ms": NOW - 500}, "observation_time_increases"),
    ({"quote_id": "quote-000000"}, "new_quote_id"),
])
def test_rejected_quotes_never_trigger_or_price_stop(change, check):
    quote = replace(QUOTE, **change)
    result = run(quote=quote)
    assert check in result["failed_checks"]
    assert not result["stop_breach_observed"]
    assert result["candidate_exit_price"] is None
    assert result["requires_human_reconciliation"]


@pytest.mark.parametrize("value", ["nan", "Infinity", "-1", "1e999", " 1", "01", "", "0.0000000000000000001"])
def test_invalid_money_rejected(value):
    with pytest.raises(ValueError):
        run(quote=replace(QUOTE, bid=value))


@pytest.mark.parametrize("change", [
    {"side": "BUY"}, {"protective_stop": "100"}, {"protective_stop": "101"},
    {"quantity": "0"}, {"point_value_cash": "0"}, {"assumed_exit_cost_cash": "-1"},
])
def test_invalid_stop_configuration_rejected(change):
    with pytest.raises(ValueError):
        run(stop=replace(STOP, **change))


def test_short_stop_must_be_above_entry():
    with pytest.raises(ValueError):
        run(stop=replace(STOP, side="SHORT"))


@pytest.mark.parametrize("now", [True, -1, 1.5, "1790000000000"])
def test_untrusted_server_clock_rejected(now):
    with pytest.raises(ValueError):
        run(now=now)


def test_policy_and_quote_sequence_reject_invalid_types():
    for policy in (replace(POLICY, previous_sequence=True), replace(POLICY, max_quote_age_ms=0),
                   replace(POLICY, max_spread_bps="10001")):
        with pytest.raises(ValueError):
            run(policy=policy)
    with pytest.raises(ValueError):
        run(quote=replace(QUOTE, sequence=True))


def test_precision_is_decimal_and_deterministic():
    quote = replace(QUOTE, bid="98.999999999999999999", ask="99.000000000000000001")
    a = run(quote=quote)
    b = run(quote=quote)
    assert a == b
    assert a["stop_breach_observed"]
    assert a["candidate_exit_price"] == "98.999999999999999999"
    assert a["candidate_pnl_cash_before_unmodeled_fees"] == "-21.250000000000000020"


def test_never_mutates_inputs_or_reserves_a_quote():
    before = (STOP, QUOTE, POLICY)
    assert run() == run()
    assert (STOP, QUOTE, POLICY) == before


@pytest.mark.parametrize("age_ms", [60_001, 600_000, 86_400_000, 8_640_000_000_000_000])
def test_caller_cannot_expand_stop_quote_age_beyond_one_minute(age_ms):
    with pytest.raises(ValueError, match="quote timing policy"):
        run(policy=replace(POLICY, max_quote_age_ms=age_ms))


def test_sixty_second_policy_ceiling_is_allowed_but_does_not_authenticate():
    result = run(policy=replace(POLICY, max_quote_age_ms=60_000))
    assert result["structural_checks_pass"]
    assert result["quote_authenticated"] is False
    assert result["may_execute_paper_order"] is False
    assert result["may_execute_real_order"] is False


@pytest.mark.parametrize("missing", [
    ("previous_sequence",),
    ("previous_observed_at_ms",),
    ("previous_quote_id",),
    ("previous_sequence", "previous_observed_at_ms"),
    ("previous_sequence", "previous_quote_id"),
    ("previous_observed_at_ms", "previous_quote_id"),
])
def test_partial_replay_checkpoint_is_rejected(missing):
    changes = {name: None for name in missing}
    with pytest.raises(ValueError, match="Incomplete previous quote checkpoint"):
        run(policy=replace(POLICY, **changes))


def test_first_observation_without_checkpoint_is_explicitly_unverified():
    first = replace(POLICY, previous_sequence=None,
                    previous_observed_at_ms=None, previous_quote_id=None)
    result = run(policy=first)
    assert result["structural_checks_pass"]
    assert result["quote_authenticated"] is False
    assert result["position_authenticated"] is False
    assert result["may_execute_paper_order"] is False
    assert result["may_execute_real_order"] is False
