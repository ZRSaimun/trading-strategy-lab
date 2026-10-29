"""Synthetic owner-review fingerprint tests: no broker requests or orders."""
from copy import deepcopy
import pytest

from app.paper_declared_owner_approval_fence import inspect_declared_owner_approval_fence

NOW = 1_800_000_000_000


def inputs():
    order = dict(client_order_id="ord1", intent_sha="a" * 64, instrument="XAUUSD",
                 side="BUY", quantity="1", stop_price="95", requested_leverage="1")
    quote = dict(instrument="XAUUSD", source="feedA", bid="99.9", ask="100",
                 observed_at_ms=NOW - 150, received_at_ms=NOW - 100)
    account = dict(broker="PAPER-LOCAL", account_alias="demo1", equity="10000",
                   free_margin="5000", daily_realized_pnl="-100", open_notional="1000",
                   open_risk="50", circuit_breaker_open=False)
    policy = dict(max_quote_age_ms=1000, max_transport_lag_ms=500,
                  max_spread_bps="100", max_slippage_bps="10", max_leverage="2",
                  max_position_loss_pct="1", max_total_open_risk_pct="5",
                  max_daily_loss_pct="5", max_notional_pct="100",
                  max_order_quantity="10", max_orders_per_window=5, order_window_ms=10000)
    return [order, quote, account, policy, [], None, [], NOW]


def reviewed():
    args = inputs()
    digest = inspect_declared_owner_approval_fence(*args)["preview_digest"]
    args[5] = dict(approval_id="approve1", approver_alias="owner1", decision="APPROVE",
                   preview_digest=digest, order_intent_sha=args[0]["intent_sha"],
                   client_order_id=args[0]["client_order_id"], broker=args[2]["broker"],
                   account_alias=args[2]["account_alias"], quote_source=args[1]["source"],
                   quote_observed_at_ms=args[1]["observed_at_ms"],
                   issued_at_ms=NOW-50, expires_at_ms=NOW+1000)
    return args


def test_no_review_holds():
    r = inspect_declared_owner_approval_fence(*inputs())
    assert r["status"] == "HOLD_DECLARED_OWNER_REVIEW"
    assert "missing_declared_owner_review" in r["failed_checks"]


def test_matching_review_still_cannot_authorize():
    r = inspect_declared_owner_approval_fence(*reviewed())
    assert r["status"] == "DECLARED_OWNER_REVIEW_UNVERIFIED"
    assert r["failed_checks"] == []
    assert r["requires_individual_owner_approval"] is True
    for k in ("owner_identity_authenticated", "approval_signature_verified",
              "approval_nonce_atomically_consumed", "broker_authenticated",
              "may_submit_paper_order", "may_submit_real_order"):
        assert r[k] is False


@pytest.mark.parametrize("field,value,check", [
    ("decision", "REJECT", "owner_review_not_positive"),
    ("preview_digest", "b" * 64, "owner_review_preview_changed"),
    ("order_intent_sha", "b" * 64, "owner_review_order_intent_sha_mismatch"),
    ("client_order_id", "ord2", "owner_review_client_order_id_mismatch"),
    ("broker", "T212-INVEST-DEMO", "owner_review_broker_mismatch"),
    ("account_alias", "other", "owner_review_account_alias_mismatch"),
    ("quote_source", "feedB", "owner_review_quote_source_mismatch"),
    ("quote_observed_at_ms", NOW-151, "owner_review_quote_observed_at_ms_mismatch"),
    ("issued_at_ms", NOW+1, "owner_review_stale_or_invalid_clock"),
    ("issued_at_ms", NOW-101, "owner_review_stale_or_invalid_clock"),
    ("expires_at_ms", NOW, "owner_review_stale_or_invalid_clock"),
    ("expires_at_ms", NOW+31_000, "owner_review_stale_or_invalid_clock"),
])
def test_declared_review_mismatch_holds(field, value, check):
    args = reviewed()
    args[5][field] = value
    r = inspect_declared_owner_approval_fence(*args)
    assert r["status"] == "HOLD_DECLARED_OWNER_REVIEW"
    assert check in r["failed_checks"]
    assert r["may_submit_real_order"] is False


def test_reused_approval_id_holds():
    args = reviewed()
    args[6] = ["approve1"]
    assert "owner_review_id_reused" in inspect_declared_owner_approval_fence(*args)["failed_checks"]


@pytest.mark.parametrize("index,key,value", [
    (0, "quantity", "2"), (1, "ask", "101"), (2, "equity", "9000"),
    (3, "max_position_loss_pct", "0.5"),
])
def test_review_binds_risk_inputs(index, key, value):
    args = reviewed()
    args[index][key] = value
    assert "owner_review_preview_changed" in inspect_declared_owner_approval_fence(*args)["failed_checks"]


def test_review_binds_order_history():
    args = reviewed()
    args[4].append(dict(client_order_id="prior", intent_sha="c" * 64,
                        submitted_at_ms=NOW-500))
    assert "owner_review_preview_changed" in inspect_declared_owner_approval_fence(*args)["failed_checks"]


def test_underlying_risk_hold_cannot_be_cleared_by_matching_review():
    args = inputs()
    args[2]["circuit_breaker_open"] = True
    digest = inspect_declared_owner_approval_fence(*args)["preview_digest"]
    approval = reviewed()[5]
    approval["preview_digest"] = digest
    args[5] = approval
    r = inspect_declared_owner_approval_fence(*args)
    assert "underlying_order_risk_hold" in r["failed_checks"]
    assert "circuit_breaker_open" in r["risk_failed_checks"]


@pytest.mark.parametrize("field,value", [
    ("decision", True), ("preview_digest", "not-a-digest"),
    ("approval_id", ""), ("issued_at_ms", True), ("expires_at_ms", -1),
])
def test_malformed_review_rejected(field, value):
    args = reviewed()
    args[5][field] = value
    with pytest.raises(ValueError):
        inspect_declared_owner_approval_fence(*args)


def test_unknown_review_field_rejected():
    args = reviewed()
    args[5]["signature"] = "fake"
    with pytest.raises(ValueError):
        inspect_declared_owner_approval_fence(*args)


def test_duplicate_or_malformed_consumed_ids_rejected():
    for consumed in (["a", "a"], [True], [""]):
        args = reviewed()
        args[6] = consumed
        with pytest.raises(ValueError):
            inspect_declared_owner_approval_fence(*args)


def test_inputs_not_mutated():
    args = reviewed()
    before = deepcopy(args)
    inspect_declared_owner_approval_fence(*args)
    assert args == before


def test_stable_fingerprint_independent_of_dictionary_insertion_order():
    args = inputs()
    first = inspect_declared_owner_approval_fence(*args)["preview_digest"]
    args[0] = dict(reversed(list(args[0].items())))
    assert inspect_declared_owner_approval_fence(*args)["preview_digest"] == first
