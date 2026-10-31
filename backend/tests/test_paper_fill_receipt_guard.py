"""Synthetic disconnected paper fill receipt audit; no brokerage credentials or requests."""
from dataclasses import replace
from decimal import Decimal
import re

import pytest

from app.paper_fill_receipt_guard import (
    FillReceipt, FillSnapshot, FillReviewPolicy, review_paper_fill_receipts,
)

NOW = 1_798_000_000_000
POLICY = FillReviewPolicy(max_position_loss_cash="150", max_total_fee_cash="10")


def fill(fid="fill-0000001", qty="1", price="100", fee="1", executed=NOW-1000, received=NOW-900):
    return FillReceipt(fid, qty, price, fee, executed, received)


def snap(*, fills=(), status="OPEN", revision=0, observed=NOW-100, **kwargs):
    base = FillSnapshot("account-0001", "client-order-0001", "XAUUSD", "HistData", "CFD-Demo",
                        "BUY", "2", "90", "1", revision, observed, status, tuple(fills))
    return replace(base, **kwargs)


def review(current, previous=None, policy=POLICY, now=NOW):
    return review_paper_fill_receipts(current, policy, server_now_ms=now, previous=previous)


def test_open_is_nonexecuting_and_no_fills():
    out = review(snap())
    assert out["structural_checks_pass"]
    assert out["remaining_quantity"] == "2"
    assert out["weighted_average_fill_price"] is None
    assert out["decision"] == "HOLD_RECONCILIATION"
    assert out["may_execute_paper_order"] is False
    assert out["may_execute_real_order"] is False
    assert out["reservation_may_be_released"] is False


def test_partial_then_filled_continuity():
    first = snap(fills=(fill(),), status="PARTIALLY_FILLED", revision=1)
    second = snap(fills=(fill(), fill("fill-0000002", "1", "102", "2", NOW-800, NOW-700)),
                  status="FILLED", revision=2, observed=NOW-50)
    out = review(second, first)
    assert out["structural_checks_pass"]
    assert out["filled_quantity"] == "2"
    assert Decimal(out["weighted_average_fill_price"]) == Decimal("101")
    assert Decimal(out["illustrative_stop_loss_including_fees_cash"]) == Decimal("25")
    assert out["broker_receipts_authenticated"] is False


@pytest.mark.parametrize("mutator,failed", [
    (lambda s: replace(s, revision=1), "revision_advances"),
    (lambda s: replace(s, observed_ms=NOW-100), "observation_advances"),
    (lambda s: replace(s, fills=(fill("fill-0000002", "1", "100", "1", NOW-800, NOW-700),)), "prior_fills_immutable"),
    (lambda s: replace(s, fills=(fill("fill-0000001", "1", "101"),)), "prior_fills_immutable"),
    (lambda s: replace(s, account_alias="account-0002"), "order_terms_immutable"),
    (lambda s: replace(s, protective_stop="89"), "order_terms_immutable"),
])
def test_continuity_fail_closed(mutator, failed):
    first = snap(fills=(fill(),), status="PARTIALLY_FILLED", revision=1)
    second = snap(fills=(fill(),), status="PARTIALLY_FILLED", revision=2, observed=NOW-50)
    out = review(mutator(second), first)
    assert failed in out["failed_checks"]
    assert out["decision"] == "HOLD_RECONCILIATION"


def test_invalid_open_regression_rejected_before_comparison():
    first = snap(fills=(fill(),), status="PARTIALLY_FILLED", revision=1)
    second = snap(fills=(fill(),), status="OPEN", revision=2, observed=NOW-50)
    with pytest.raises(ValueError, match="Open order"):
        review(second, first)


def test_terminal_state_cannot_regress():
    first = snap(fills=(fill("fill-0000001", "2"),), status="FILLED", revision=1)
    second = replace(first, order_status="CANCELED", revision=2, observed_ms=NOW-50)
    assert "terminal_state_immutable" in review(second, first)["failed_checks"]


def test_new_backdated_fill_quarantined():
    first = snap(fills=(fill(),), status="PARTIALLY_FILLED", revision=1)
    second = snap(fills=(fill(), fill("fill-0000002", "1", "101", "1", NOW-1100, NOW-1000)),
                  status="FILLED", revision=2, observed=NOW-50)
    with pytest.raises(ValueError, match="Out-of-order"):
        review(second, first)


@pytest.mark.parametrize("fills,status,error", [
    ((fill(), fill()), "FILLED", "Duplicate fill"),
    ((fill("fill-0000001", "3"),), "FILLED", "exceed"),
    ((), "FILLED", "Missing fill"),
    ((fill(),), "OPEN", "Open order"),
    ((fill(),), "REJECTED", "Rejected"),
    ((fill(),), "FILLED", "Filled status"),
    ((fill("fill-0000001", "2"),), "PARTIALLY_FILLED", "Partial status"),
    ((fill("fill-0000001", "1", "90"),), "PARTIALLY_FILLED", "Protective stop"),
    ((fill("fill-0000001", "1", "100", "1", NOW-1000, NOW+1),), "PARTIALLY_FILLED", "Future"),
    ((fill("fill-0000001", "1", "100", "1", NOW-20_000, NOW-900),), "PARTIALLY_FILLED", "latency"),
])
def test_malformed_population_rejected(fills, status, error):
    with pytest.raises(ValueError, match=error):
        review(snap(fills=fills, status=status))


@pytest.mark.parametrize("value", ["nan", "inf", "1e4", "-1", "0.0000000000001", " 1", "1,000", "9999999999999999999", 1.0, True])
def test_invalid_money_fail_closed(value):
    with pytest.raises(ValueError):
        review(snap(fills=(fill(qty=value),), status="PARTIALLY_FILLED"))


def test_short_stop_and_loss():
    s = snap(side="SELL", protective_stop="110", fills=(fill("fill-0000001", "2", "100", "2"),), status="FILLED")
    out = review(s)
    assert out["structural_checks_pass"]
    assert Decimal(out["illustrative_stop_loss_including_fees_cash"]) == 22


def test_stop_wrong_side_for_short_rejected():
    with pytest.raises(ValueError, match="Protective stop"):
        review(snap(side="SELL", fills=(fill(),), status="PARTIALLY_FILLED"))


def test_stale_snapshot_and_unknown_state_fail_checks():
    s = snap(observed=NOW-6000, status="UNKNOWN")
    out = review(s)
    assert set(out["failed_checks"]) == {"current_snapshot_fresh", "known_order_state"}


def test_fee_and_loss_caps_fail_checks():
    out = review(snap(fills=(fill("fill-0000001", "1", "300", "11"),), status="PARTIALLY_FILLED"))
    assert set(out["failed_checks"]) == {"fee_cap", "stressed_stop_loss_cap"}


def test_canceled_partial_retains_exposure_and_no_release():
    out = review(snap(fills=(fill(),), status="CANCELED"))
    assert out["filled_quantity"] == "1"
    assert out["remaining_quantity"] == "1"
    assert out["reservation_may_be_released"] is False


def test_fingerprint_stable_under_equivalent_decimal_format():
    a = snap(fills=(fill(qty="1", price="100", fee="1"),), status="PARTIALLY_FILLED")
    b = snap(fills=(fill(qty="1.0", price="100.00", fee="1.00"),), status="PARTIALLY_FILLED")
    assert review(a)["receipt_population_sha256"] == review(b)["receipt_population_sha256"]
    assert re.fullmatch(r"[0-9a-f]{64}", review(a)["receipt_population_sha256"])
    assert "account-0001" not in str(review(a))


def test_replay_fill_receipt_or_order_ids_rejected():
    with pytest.raises(ValueError):
        review(snap(order_alias="x"))
    with pytest.raises(ValueError):
        review(snap(fills=(fill(fid="bad"),), status="PARTIALLY_FILLED"))


def test_future_snapshot_rejected_by_check():
    out = review(snap(observed=NOW+1))
    assert out["failed_checks"] == ["current_snapshot_fresh"]


def test_bool_timestamp_and_float_quantity_rejected():
    with pytest.raises(ValueError):
        review(snap(observed=True))
    with pytest.raises(ValueError):
        review(snap(fills=(fill(qty=1.0),), status="PARTIALLY_FILLED"))


def test_no_network_database_or_execution_symbols():
    import inspect
    import app.paper_fill_receipt_guard as module
    source = inspect.getsource(module)
    for prohibited in ("requests.post", "httpx.post", "Session(", "submit_order("):
        assert prohibited not in source


def test_fingerprint_binds_protective_stop_and_requested_quantity():
    a = snap(fills=(fill(),), status="PARTIALLY_FILLED")
    assert review(a)["receipt_population_sha256"] != review(replace(a, protective_stop="89"))["receipt_population_sha256"]
    assert review(a)["receipt_population_sha256"] != review(replace(a, requested_quantity="3"))["receipt_population_sha256"]


def test_backdated_new_fill_detected_even_when_sorted():
    first = snap(fills=(fill("fill-0000001", "1", "100", "1", NOW-800, NOW-700),),
                 status="PARTIALLY_FILLED", revision=1)
    second = snap(fills=(fill("fill-0000002", "1", "101", "1", NOW-900, NOW-850),
                         fill("fill-0000001", "1", "100", "1", NOW-800, NOW-700)),
                  status="FILLED", revision=2, observed=NOW-50)
    assert "new_fills_not_backdated" in review(second, first)["failed_checks"]


@pytest.mark.parametrize("policy", [
    FillReviewPolicy(max_fills=0), FillReviewPolicy(max_fills=True),
    FillReviewPolicy(max_snapshot_age_ms=0), FillReviewPolicy(max_receipt_lag_ms=0),
    FillReviewPolicy(max_total_fee_cash="NaN"), FillReviewPolicy(max_position_loss_cash="0"),
])
def test_invalid_policy_rejected(policy):
    with pytest.raises(ValueError):
        review(snap(), policy=policy)


def test_fresh_prior_not_required_but_future_prior_fails_check():
    first = snap(observed=NOW+1)
    second = snap(revision=1, observed=NOW+2)
    out = review(second, first)
    assert "previous_snapshot_not_future" in out["failed_checks"]
