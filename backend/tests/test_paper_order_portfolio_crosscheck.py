"""Synthetic cross-guard integration: no credentials, network, broker or orders."""
from copy import deepcopy

import pytest

from app.paper_order_portfolio_crosscheck import evaluate_paper_order_portfolio_crosscheck

NOW = 1_800_000_000_000


def fixtures():
    candidate = dict(
        client_order_id="paper-order-0001", instrument="TEST-EQUITY",
        provider="DECLARED", venue="SIM", state="PENDING", side="LONG",
        quantity="2", entry_price="100.02", stop_price="99",
        stressed_exit_price="98", point_value_cash="1",
        estimated_total_cost_cash="0.5", margin_rate_percent="100",
        bid="100", ask="100.02", quote_observed_at_ms=NOW - 200,
        quote_received_at_ms=NOW - 100,
    )
    other = dict(
        client_order_id="paper-order-0002", instrument="OTHER-EQ",
        provider="DECLARED", venue="SIM", state="OPEN", side="LONG",
        quantity="1", entry_price="50.02", stop_price="49",
        stressed_exit_price="48", point_value_cash="1",
        estimated_total_cost_cash="0.2", margin_rate_percent="100",
        bid="50", ask="50.02", quote_observed_at_ms=NOW - 200,
        quote_received_at_ms=NOW - 100,
    )
    snapshot = dict(
        account_id="paper-account-1", currency="GBP",
        equity_cash="10000", daily_realized_pnl_cash="-20",
        daily_unrealized_pnl_cash="-10", max_daily_loss_cash="500",
        max_position_loss_cash="100", max_gross_leverage="1",
        max_margin_fraction="0.9", max_symbol_notional_cash="5000",
        max_open_or_pending_orders=10, max_orders_per_symbol=3,
        max_quote_age_ms=3000, max_transport_lag_ms=1000,
        max_spread_bps="20", emergency_latched=False,
        market_session_open=True, exposures=[candidate, other],
    )
    order = dict(
        broker="Trading212-Invest", account_alias="paper-account-1",
        instrument="TEST-EQUITY", venue="SIM", quote_provider="DECLARED",
        direction="BUY", client_order_id="paper-order-0001",
        quote_id="declared-quote-0001", currency="GBP",
        quantity="2", entry_price="100.02", stop_price="99",
        stressed_exit_price="98", point_value_cash="1",
        estimated_total_cost_cash="0.5", account_equity_cash="10000",
        existing_gross_notional_cash="50.02",
        existing_reserved_margin_cash="50.02",
        existing_reserved_risk_cash="2.22",
        daily_realized_pnl_cash="-20", daily_unrealized_pnl_cash="-10",
        max_position_loss_cash="100", max_daily_loss_cash="500",
        max_gross_leverage="1", margin_rate_percent="100",
        quote_bid="100", quote_ask="100.02", max_spread_bps="20",
        quote_observed_at_ms=NOW - 200,
        quote_received_at_ms=NOW - 100,
    )
    policy = dict(
        instrument_groups={"TEST-EQUITY": "EQUITIES", "OTHER-EQ": "EQUITIES"},
        group_notional_caps_cash={"EQUITIES": "2000"},
        max_group_share_of_stressed_equity="0.5",
    )
    return order, snapshot, policy


def run(order=None, snapshot=None, policy=None, now_ms=NOW):
    o, s, p = fixtures()
    return evaluate_paper_order_portfolio_crosscheck(
        o if order is None else order,
        s if snapshot is None else snapshot,
        p if policy is None else policy, now_ms=now_ms,
    )


def test_consistent_assumptions_never_grant_execution():
    out = run()
    assert out["structural_checks_pass"] is True, out["failed_checks"]
    assert out["status"] == "HOLD_RECONCILIATION"
    assert out["candidate_stressed_loss_cash"] == "4.54"
    assert out["quote_authenticated"] is False
    assert out["risk_reservation_committed"] is False
    assert out["owner_approval_verified"] is False
    assert out["may_execute_real_order"] is False
    assert out["may_execute_paper_order"] is False


@pytest.mark.parametrize("field,value,check", [
    ("account_alias", "other-account", "account_identity_and_currency"),
    ("currency", "USD", "account_identity_and_currency"),
    ("instrument", "OTHER-EQ", "candidate_source_and_side"),
    ("quote_provider", "OTHER", "candidate_source_and_side"),
    ("venue", "OTHER", "candidate_source_and_side"),
    ("direction", "SELL", "candidate_source_and_side"),
    ("quantity", "2.1", "candidate_prices_quantity_and_costs"),
    ("quote_ask", "100.03", "candidate_prices_quantity_and_costs"),
    ("entry_price", "100.03", "candidate_prices_quantity_and_costs"),
    ("stop_price", "98.5", "candidate_prices_quantity_and_costs"),
    ("estimated_total_cost_cash", "0.6", "candidate_prices_quantity_and_costs"),
    ("quote_observed_at_ms", NOW - 300, "candidate_quote_identity_fields"),
    ("account_equity_cash", "11000", "account_risk_policy_and_pnl"),
    ("max_daily_loss_cash", "400", "account_risk_policy_and_pnl"),
    ("existing_gross_notional_cash", "0", "other_notional_margin_and_risk_reconciled"),
    ("existing_reserved_margin_cash", "0", "other_notional_margin_and_risk_reconciled"),
    ("existing_reserved_risk_cash", "0", "other_notional_margin_and_risk_reconciled"),
])
def test_cross_guard_drift_blocks(field, value, check):
    order, snapshot, policy = fixtures()
    order[field] = value
    out = run(order, snapshot, policy)
    assert "crosscheck." + check in out["failed_checks"]
    assert not out["structural_checks_pass"]
    assert not out["may_execute_real_order"]


@pytest.mark.parametrize("field,value,check", [
    ("max_quote_age_ms", 5000, "independent_conservative_policy_ceiling"),
    ("max_transport_lag_ms", 1500, "independent_conservative_policy_ceiling"),
    ("max_spread_bps", "101", "independent_conservative_policy_ceiling"),
    ("max_gross_leverage", "6", "independent_conservative_policy_ceiling"),
    ("max_position_loss_cash", "501", "independent_conservative_policy_ceiling"),
    ("max_daily_loss_cash", "1001", "independent_conservative_policy_ceiling"),
])
def test_independent_policy_ceiling_blocks_even_if_underlying_guard_allows(field, value, check):
    order, snapshot, policy = fixtures()
    snapshot[field] = value
    if field in ("max_spread_bps", "max_gross_leverage",
                 "max_position_loss_cash", "max_daily_loss_cash"):
        mapping = {"max_spread_bps": "max_spread_bps",
                   "max_gross_leverage": "max_gross_leverage",
                   "max_position_loss_cash": "max_position_loss_cash",
                   "max_daily_loss_cash": "max_daily_loss_cash"}
        order[mapping[field]] = value
    # The account guard requires position <= daily <= equity.
    if field == "max_position_loss_cash":
        snapshot["max_daily_loss_cash"] = "1000"
        order["max_daily_loss_cash"] = "1000"
    out = run(order, snapshot, policy)
    assert "crosscheck." + check in out["failed_checks"]
    assert not out["structural_checks_pass"]


def test_missing_or_duplicate_candidate_and_nonpending_state_hold():
    o, s, p = fixtures()
    s["exposures"][0]["client_order_id"] = "paper-order-0003"
    assert "crosscheck.candidate_exactly_once_and_pending" in run(o, s, p)["failed_checks"]
    o, s, p = fixtures()
    duplicate = deepcopy(s["exposures"][0])
    s["exposures"].append(duplicate)
    out = run(o, s, p)
    assert "crosscheck.candidate_exactly_once_and_pending" in out["failed_checks"]
    assert "portfolio.unique_client_order_ids" in out["failed_checks"]
    o, s, p = fixtures()
    s["exposures"][0]["state"] = "OUTCOME_UNKNOWN"
    out = run(o, s, p)
    assert "crosscheck.candidate_exactly_once_and_pending" in out["failed_checks"]
    assert "portfolio.no_uncertain_order_outcomes" in out["failed_checks"]


def test_breached_stop_and_stale_quote_hold():
    o, s, p = fixtures()
    s["exposures"][1]["bid"] = "48"
    out = run(o, s, p)
    assert "portfolio.no_breached_protective_stops" in out["failed_checks"]
    o, s, p = fixtures()
    o["quote_observed_at_ms"] = NOW - 4000
    s["exposures"][0]["quote_observed_at_ms"] = NOW - 4000
    out = run(o, s, p)
    assert "review.quote_fresh" in out["failed_checks"]
    assert "portfolio.all_quotes_fresh_and_uncrossed" in out["failed_checks"]


def test_emergency_latch_group_cap_and_unsupported_cfd_hold():
    o, s, p = fixtures()
    s["emergency_latched"] = True
    assert "portfolio.emergency_latch_clear" in run(o, s, p)["failed_checks"]
    o, s, p = fixtures()
    p["group_notional_caps_cash"]["EQUITIES"] = "200"
    assert "portfolio.declared_group_notional_within_cap" in run(o, s, p)["failed_checks"]
    o, s, p = fixtures()
    o["broker"] = "Trading212-CFD"
    assert "review.official_api_account_supported" in run(o, s, p)["failed_checks"]


def test_unknown_fields_rejected_and_inputs_not_mutated():
    o, s, p = fixtures()
    before = deepcopy((o, s, p))
    first = run(o, s, p)
    assert (o, s, p) == before
    assert first == run(o, s, p)
    o["api_key"] = "never"
    with pytest.raises(ValueError):
        run(o, s, p)


def test_fingerprint_changes_with_policy_inventory_and_clock():
    o, s, p = fixtures()
    baseline = run(o, s, p)
    s["exposures"][1]["quantity"] = "1.1"
    assert run(o, s, p)["crosscheck_sha256"] != baseline["crosscheck_sha256"]
    o, s, p = fixtures()
    p["group_notional_caps_cash"]["EQUITIES"] = "1999"
    assert run(o, s, p)["crosscheck_sha256"] != baseline["crosscheck_sha256"]
    assert run(now_ms=NOW + 1)["crosscheck_sha256"] != baseline["crosscheck_sha256"]


def test_boolean_clock_and_malformed_decimal_rejected():
    o, s, p = fixtures()
    with pytest.raises(ValueError):
        run(o, s, p, now_ms=True)
    o["quantity"] = 2.0
    with pytest.raises(ValueError):
        run(o, s, p)


def test_cash_account_leverage_above_one_blocks_cross_guard_review():
    # A >1x policy may be internally funded on this one trade but is not a
    # valid unleveraged Invest-account declaration for the offline reviewer.
    order, snapshot, policy = fixtures()
    order["max_gross_leverage"] = "2"
    snapshot["max_gross_leverage"] = "2"
    result = run(order, snapshot, policy)
    assert "review.cash_account_unleveraged_policy" in result["failed_checks"]
    assert "crosscheck.both_guards_structurally_pass" in result["failed_checks"]
    assert result["structural_checks_pass"] is False
    assert result["may_execute_paper_order"] is False
    assert result["may_execute_real_order"] is False
