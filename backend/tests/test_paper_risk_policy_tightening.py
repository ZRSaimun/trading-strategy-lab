"""Synthetic risk-policy change tests: no broker, database or order sender."""
from copy import deepcopy
import pytest
from app.paper_risk_policy_tightening import review_paper_risk_policy_tightening

NOW = 1_800_000_000_000


def policy(**changes):
    data = dict(version=1, account_alias="paper-account-01", provider="TEST-BROKER",
                currency="GBP", revision=3, effective_at_ms=NOW-1000,
                emergency_latched=False, max_position_loss_cash="20",
                max_daily_loss_cash="100", max_gross_notional_cash="10000",
                max_margin_cash="500", max_gross_leverage="2",
                max_margin_fraction="0.5", max_quote_age_ms=3000,
                max_transport_lag_ms=1000, max_spread_bps="20",
                max_open_or_pending_orders=10, max_orders_per_symbol=5,
                max_orders_per_hour=15, max_orders_per_day=50,
                min_order_cooldown_ms=5000, max_consecutive_losses=3)
    data.update(changes)
    return data


def next_policy(**changes):
    return policy(**{**dict(revision=4, effective_at_ms=NOW-500), **changes})


def review(**changes):
    return review_paper_risk_policy_tightening(policy(), next_policy(**changes), now_ms=NOW)


def test_equal_caps_do_not_grant_permission():
    r = review()
    assert r["assumption_checks_pass"] and not r["failed_checks"]
    assert r["status"] == "HOLD_RECONCILIATION"
    assert r["source_authenticated"] is False
    assert r["policy_persisted"] is False
    assert r["owner_approval_recorded"] is False
    assert r["may_execute_paper_order"] is False
    assert r["may_execute_real_order"] is False
    assert r["may_clear_emergency_latch"] is False


@pytest.mark.parametrize("field,value", [
    ("max_position_loss_cash", "10"), ("max_daily_loss_cash", "90"),
    ("max_gross_notional_cash", "9000"), ("max_margin_cash", "400"),
    ("max_gross_leverage", "1"), ("max_margin_fraction", "0.4"),
    ("max_quote_age_ms", 2000), ("max_transport_lag_ms", 500),
    ("max_spread_bps", "10"), ("max_open_or_pending_orders", 8),
    ("max_orders_per_symbol", 4), ("max_orders_per_hour", 10),
    ("max_orders_per_day", 40), ("min_order_cooldown_ms", 7000),
    ("max_consecutive_losses", 2), ("emergency_latched", True),
])
def test_tightening_is_structurally_accepted_but_not_authorized(field, value):
    r = review(**{field: value})
    assert r["assumption_checks_pass"]
    assert not r["may_execute_real_order"]


@pytest.mark.parametrize("field,value,check", [
    ("max_position_loss_cash", "21", "max_position_loss_cash_not_relaxed"),
    ("max_daily_loss_cash", "101", "max_daily_loss_cash_not_relaxed"),
    ("max_gross_notional_cash", "10001", "max_gross_notional_cash_not_relaxed"),
    ("max_margin_cash", "501", "max_margin_cash_not_relaxed"),
    ("max_gross_leverage", "2.01", "max_gross_leverage_not_relaxed"),
    ("max_margin_fraction", "0.51", "max_margin_fraction_not_relaxed"),
    ("max_quote_age_ms", 3001, "invalid"),
    ("max_transport_lag_ms", 1001, "invalid"),
    ("max_spread_bps", "21", "max_spread_bps_not_relaxed"),
    ("max_open_or_pending_orders", 11, "max_open_or_pending_orders_not_relaxed"),
    ("max_orders_per_symbol", 6, "max_orders_per_symbol_not_relaxed"),
    ("max_orders_per_hour", 16, "max_orders_per_hour_not_relaxed"),
    ("max_orders_per_day", 51, "max_orders_per_day_not_relaxed"),
    ("min_order_cooldown_ms", 4999, "cooldown_not_shortened"),
    ("max_consecutive_losses", 4, "max_consecutive_losses_not_relaxed"),
])
def test_relaxation_fails_closed(field, value, check):
    if check == "invalid":
        with pytest.raises(ValueError):
            review(**{field: value})
    else:
        assert check in review(**{field: value})["failed_checks"]


def test_latch_cannot_be_cleared_even_with_other_tightenings():
    r = review_paper_risk_policy_tightening(
        policy(emergency_latched=True), next_policy(max_position_loss_cash="1"), now_ms=NOW)
    assert "emergency_latch_never_cleared" in r["failed_checks"]


@pytest.mark.parametrize("change,check", [
    ({"revision": 3}, "next_revision"),
    ({"revision": 5}, "next_revision"),
    ({"effective_at_ms": NOW-1000}, "effective_time_monotonic"),
    ({"effective_at_ms": NOW+1}, "effective_time_monotonic"),
])
def test_replay_and_clock_rejected(change, check):
    assert check in review(**change)["failed_checks"]


@pytest.mark.parametrize("change", [
    {"account_alias": "other-account-1"}, {"provider": "OTHER-BROKER"},
    {"currency": "USD"},
])
def test_identity_changes_rejected(change):
    with pytest.raises(ValueError, match="account/provider/currency"):
        review(**change)


@pytest.mark.parametrize("change", [
    {"version": True}, {"revision": True}, {"effective_at_ms": 1.5},
    {"emergency_latched": 0}, {"max_position_loss_cash": 1.0},
    {"max_daily_loss_cash": "1e2"}, {"max_margin_fraction": "NaN"},
    {"max_gross_leverage": "101"}, {"max_orders_per_hour": True},
    {"max_spread_bps": " 20"}, {"max_daily_loss_cash": "10"},
    {"max_orders_per_symbol": 11}, {"max_orders_per_day": 10},
    {"unexpected_field": "secret"},
])
def test_malformed_policy_rejected(change):
    with pytest.raises(ValueError):
        review(**change)


def test_missing_field_rejected():
    doc = next_policy()
    del doc["max_margin_cash"]
    with pytest.raises(ValueError):
        review_paper_risk_policy_tightening(policy(), doc, now_ms=NOW)


@pytest.mark.parametrize("clock", [True, 1.0, -1, 8_640_000_000_000_001])
def test_bad_clock_rejected(clock):
    with pytest.raises(ValueError):
        review_paper_risk_policy_tightening(policy(), next_policy(), now_ms=clock)


def test_previous_future_or_revision_exhaustion_rejected():
    with pytest.raises(ValueError, match="future-dated"):
        review_paper_risk_policy_tightening(policy(effective_at_ms=NOW+1), next_policy(), now_ms=NOW)
    with pytest.raises(ValueError, match="exhausted"):
        review_paper_risk_policy_tightening(policy(revision=2**53-1), next_policy(), now_ms=NOW)


def test_hash_binds_policy_identity_revision_time_and_inputs_without_mutation():
    previous, proposed = policy(), next_policy()
    original = deepcopy((previous, proposed))
    first = review_paper_risk_policy_tightening(previous, proposed, now_ms=NOW)
    assert first == review_paper_risk_policy_tightening(previous, proposed, now_ms=NOW)
    assert (previous, proposed) == original
    assert first["review_sha256"] != review(max_position_loss_cash="19")["review_sha256"]
    assert first["review_sha256"] != review_paper_risk_policy_tightening(
        previous, proposed, now_ms=NOW+1)["review_sha256"]
    assert first["review_sha256"] != review_paper_risk_policy_tightening(
        policy(account_alias="other-account-1"), next_policy(account_alias="other-account-1"),
        now_ms=NOW)["review_sha256"]
