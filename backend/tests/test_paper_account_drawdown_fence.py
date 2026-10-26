"""Synthetic, disconnected paper account drawdown tests; never broker orders."""
from copy import deepcopy
from datetime import datetime, timezone
import pytest

from app.paper_account_drawdown_fence import review_paper_account_drawdown

NOW = 1_793_049_600_000  # 2026-10-27 UTC
DAY = datetime.fromtimestamp(NOW / 1000, tz=timezone.utc).date().isoformat()


def policy(**kw):
    return dict(
        account_alias="paper-account-01", provider="TEST-BROKER", currency="GBP",
        max_peak_drawdown_pct="10", max_intraday_drawdown_pct="5",
        min_free_equity_pct="20", max_consecutive_losses=3,
        **kw,
    )


def snapshot(*, sequence=2, observed_ms=NOW - 500, received_ms=NOW - 400,
             balance_cash="1000", unrealized_pnl_cash="-20",
             equity_cash="980", used_margin_cash="100",
             reserved_risk_cash="10", peak_equity_cash="1020",
             day_start_equity_cash="1000", consecutive_losses=1,
             **kw):
    return dict(
        account_alias="paper-account-01", provider="TEST-BROKER",
        currency="GBP", sequence=sequence, observed_ms=observed_ms,
        received_ms=received_ms, utc_day=DAY,
        balance_cash=balance_cash, unrealized_pnl_cash=unrealized_pnl_cash,
        equity_cash=equity_cash, used_margin_cash=used_margin_cash,
        reserved_risk_cash=reserved_risk_cash,
        peak_equity_cash=peak_equity_cash,
        day_start_equity_cash=day_start_equity_cash,
        consecutive_losses=consecutive_losses,
        **kw,
    )


def previous():
    return snapshot(sequence=1, observed_ms=NOW - 900,
                    received_ms=NOW - 800,
                    balance_cash="1000", unrealized_pnl_cash="-10",
                    equity_cash="990", consecutive_losses=1)


def review(*, p=None, old=None, current=None, now=NOW, **kw):
    return review_paper_account_drawdown(
        policy() if p is None else p,
        snapshot() if current is None else current,
        now_ms=now, previous=previous() if old is None else old, **kw)


def test_clean_structural_review_still_cannot_trade():
    x = review()
    assert x["assumption_checks_pass"] is True
    assert x["status"] == "HOLD_RECONCILIATION"
    assert x["may_execute_real_order"] is False
    assert x["may_execute_paper_order"] is False
    assert x["account_authenticated"] is False
    assert x["free_equity_cash"] == "870"
    assert x["stressed_peak_drawdown_pct"].startswith("4.9019607")
    assert x["stressed_intraday_drawdown_pct"] == "3"
    assert len(x["review_sha256"]) == 64


@pytest.mark.parametrize("field,changed,failed", [
    ("sequence", 1, "sequence_contiguous"),
    ("sequence", 4, "sequence_contiguous"),
    ("observed_ms", NOW - 1200, "observation_monotonic"),
    ("received_ms", NOW + 1, "snapshot_time_order"),
    ("observed_ms", NOW - 3500, "snapshot_fresh"),
    ("received_ms", NOW - 100, "transport_lag_ok"),
    ("peak_equity_cash", "1000", "peak_not_reset"),
    ("day_start_equity_cash", "999", "day_start_not_reset"),
    ("consecutive_losses", 0, "loss_streak_not_reset_without_receipt"),
    ("consecutive_losses", 3, "loss_streak_below_threshold"),
    ("balance_cash", "999", "checkpoint_equity_reconciles"),
    ("used_margin_cash", "900", "margin_buffer_within_policy"),
    ("reserved_risk_cash", "60", "intraday_drawdown_within_cap"),
    ("unrealized_pnl_cash", "-150", "checkpoint_equity_reconciles"),
    ("provider", "OTHER", "account_identity_matches"),
    ("currency", "USD", "account_identity_matches"),
])
def test_each_breach_holds(field, changed, failed):
    c = snapshot()
    c[field] = changed
    x = review(current=c)
    assert failed in x["failed_checks"]
    assert x["assumption_checks_pass"] is False
    assert x["may_execute_real_order"] is False


def test_missing_checkpoint_never_establishes_clean_continuity():
    x = review_paper_account_drawdown(policy(), snapshot(), now_ms=NOW)
    assert "prior_checkpoint_present" in x["failed_checks"]
    assert not x["assumption_checks_pass"]


def test_day_rollover_never_silently_resets_limits():
    old = previous()
    old["utc_day"] = "2026-10-26"
    old["observed_ms"] -= 86_400_000
    old["received_ms"] -= 86_400_000
    x = review(old=old)
    assert "same_utc_day" in x["failed_checks"]


def test_peak_drawdown_and_stressed_equity_block_even_when_cash_equity_positive():
    c = snapshot(balance_cash="1000", unrealized_pnl_cash="-70",
                 equity_cash="930", peak_equity_cash="1050",
                 reserved_risk_cash="5")
    x = review(current=c)
    assert "peak_drawdown_within_cap" in x["failed_checks"]
    assert "intraday_drawdown_within_cap" in x["failed_checks"]


def test_identity_and_snapshot_digest_is_stable_and_nonmutating():
    p, c, old = policy(), snapshot(), previous()
    before = deepcopy((p, c, old))
    a = review(p=p, current=c, old=old)
    b = review(p=p, current=c, old=old)
    assert a == b
    assert before == (p, c, old)
    c["reserved_risk_cash"] = "11"
    assert review(p=p, current=c, old=old)["review_sha256"] != a["review_sha256"]


@pytest.mark.parametrize("field,value", [
    ("max_peak_drawdown_pct", "20.0001"),
    ("max_intraday_drawdown_pct", "11"),
    ("min_free_equity_pct", "9"),
    ("max_consecutive_losses", True),
    ("max_peak_drawdown_pct", "NaN"),
    ("max_peak_drawdown_pct", 5.0),
])
def test_unsafe_policy_rejected(field, value):
    p = policy()
    p[field] = value
    with pytest.raises(ValueError):
        review(p=p)


@pytest.mark.parametrize("field,value", [
    ("sequence", True),
    ("equity_cash", "1e3"),
    ("equity_cash", "-1"),
    ("equity_cash", "NaN"),
    ("reserved_risk_cash", "-1"),
    ("utc_day", "2026-02-30"),
    ("account_alias", "bad alias"),
])
def test_malformed_snapshot_rejected(field, value):
    c = snapshot()
    c[field] = value
    with pytest.raises(ValueError):
        review(current=c)


def test_unknown_fields_rejected_and_stricter_freshness_only():
    c = snapshot()
    c["allow_execution"] = True
    with pytest.raises(ValueError):
        review(current=c)
    with pytest.raises(ValueError):
        review(max_snapshot_age_ms=3001)
    with pytest.raises(ValueError):
        review(max_transport_lag_ms=1001)
    with pytest.raises(ValueError):
        review(now=True)


def test_old_checkpoint_corruption_cannot_be_hidden():
    old = previous()
    old["equity_cash"] = "900"
    x = review(old=old)
    assert "checkpoint_equity_reconciles" in x["failed_checks"]


def test_baseline_below_equity_is_not_a_valid_peak():
    c = snapshot(balance_cash="1100", unrealized_pnl_cash="0",
                 equity_cash="1100")
    x = review(current=c)
    assert "baselines_cover_observed_equity" in x["failed_checks"]


def test_equality_at_drawdown_cap_is_a_breach():
    c = snapshot(balance_cash="1000", unrealized_pnl_cash="-50",
                 equity_cash="950", peak_equity_cash="1020",
                 reserved_risk_cash="0")
    x = review(current=c)
    assert "intraday_drawdown_within_cap" in x["failed_checks"]
