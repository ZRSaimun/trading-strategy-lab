"""Synthetic, disconnected as-of quote-tape continuity tests."""
from copy import deepcopy
import random

import pytest

from app.offline_demo_quote_tape_simulator import fingerprint_demo_quote_tape
from app.offline_demo_quote_tape_continuity import audit_declared_demo_quote_tape_continuity


def fixture():
    scope = dict(provider="Synthetic", venue="DEMO", account_alias="a1",
                 instrument="XAUUSD-CFD", quote_currency="USD", point_value_cash="1",
                 max_quote_age_ms=100, max_spread_price="3", adverse_slippage_price="0.5",
                 commission_per_contract_side="0.1", as_of_ms=155)
    intent = dict(client_order_id="o1", side="BUY", kind="MARKET", requested_contracts=5,
                  limit_price=None, submitted_at_ms=100, eligible_after_ms=120,
                  expires_at_ms=900, cancel_requested_at_ms=None, cancel_effective_at_ms=None)
    quote = dict(quote_id="q1", provider="Synthetic", venue="DEMO", account_alias="a1",
                 instrument="XAUUSD-CFD", observed_at_ms=140, received_at_ms=150,
                 bid="100", ask="102", available_contracts=2)
    next_quote = dict(quote, quote_id="q2", observed_at_ms=160, received_at_ms=170,
                      bid="101", ask="103", available_contracts=4)
    newer = dict(scope, as_of_ms=250)
    return [scope, intent, [quote], newer, deepcopy(intent), [deepcopy(quote), next_quote]]


def run(parts, *, prior_hash=None, later_hash=None):
    s1, i1, q1, s2, i2, q2 = parts
    return audit_declared_demo_quote_tape_continuity(
        s1, i1, q1, fingerprint_demo_quote_tape(s1, q1) if prior_hash is None else prior_hash,
        s2, i2, q2, fingerprint_demo_quote_tape(s2, q2) if later_hash is None else later_hash)


def test_append_only_recomputes_partial_fill_and_keeps_execution_disabled():
    result = run(fixture())
    assert result["earlier_hypothetical_filled_contracts"] == 2
    assert result["later_hypothetical_filled_contracts"] == 5
    assert result["new_hypothetical_filled_contracts"] == 3
    assert result["earlier_quote_count"] == 1 and result["later_quote_count"] == 2
    assert result["prior_fills_preserved"]
    assert result["broker_fills_authenticated"] is False
    assert result["broker_quote_population_complete"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert run(fixture()) == result


def test_no_new_quotes_is_allowed_as_time_advances():
    parts = fixture()
    parts[-1].pop()
    result = run(parts)
    assert result["new_hypothetical_filled_contracts"] == 0


def test_future_quote_observed_before_cutoff_but_received_after_is_not_lookahead():
    parts = fixture()
    parts[-1][-1]["observed_at_ms"] = 151
    assert run(parts)["new_hypothetical_filled_contracts"] == 3


def test_cancellation_after_cutoff_preserves_prior_fill():
    parts = fixture()
    parts[4]["cancel_requested_at_ms"] = 156
    parts[4]["cancel_effective_at_ms"] = 165
    assert run(parts)["new_hypothetical_filled_contracts"] == 0


def test_cancellation_after_second_quote_allows_second_fill():
    parts = fixture()
    parts[4]["cancel_requested_at_ms"] = 171
    parts[4]["cancel_effective_at_ms"] = 180
    assert run(parts)["new_hypothetical_filled_contracts"] == 3


@pytest.mark.parametrize("field,value", [
    ("provider", "Other"), ("venue", "LIVE"), ("account_alias", "a2"),
    ("instrument", "NSXUSD-CFD"), ("quote_currency", "GBP"),
    ("point_value_cash", "2"), ("max_quote_age_ms", 50),
    ("max_spread_price", "4"), ("adverse_slippage_price", "0.2"),
    ("commission_per_contract_side", "0.2"),
])
def test_scope_identity_and_cost_policy_immutable(field, value):
    parts = fixture()
    parts[3][field] = value
    if field in ("provider", "venue", "account_alias", "instrument"):
        for quote in parts[-1]:
            quote[field] = value
    with pytest.raises(ValueError, match="Source identity or execution-cost policy changed"):
        run(parts)


@pytest.mark.parametrize("field,value", [
    ("client_order_id", "other"), ("side", "SELL"), ("kind", "LIMIT"),
    ("requested_contracts", 4), ("submitted_at_ms", 101),
    ("eligible_after_ms", 121), ("expires_at_ms", 800),
])
def test_order_intent_cannot_be_rewritten(field, value):
    parts = fixture()
    parts[4][field] = value
    if field == "kind":
        parts[4]["limit_price"] = "103"
    with pytest.raises(ValueError, match="Previously declared order intent changed"):
        run(parts)


def test_cannot_backdate_cancellation():
    parts = fixture()
    parts[4]["cancel_requested_at_ms"] = 155
    parts[4]["cancel_effective_at_ms"] = 180
    with pytest.raises(ValueError, match="Cancellation changed or was backdated"):
        run(parts)


def test_cannot_erase_existing_cancellation():
    parts = fixture()
    parts[1]["cancel_requested_at_ms"] = 130
    parts[1]["cancel_effective_at_ms"] = 150
    with pytest.raises(ValueError, match="Cancellation changed or was backdated"):
        run(parts)


def test_cannot_change_existing_cancellation():
    parts = fixture()
    for intent in (parts[1], parts[4]):
        intent["cancel_requested_at_ms"] = 130
        intent["cancel_effective_at_ms"] = 150
    parts[4]["cancel_effective_at_ms"] = 151
    with pytest.raises(ValueError, match="Cancellation changed or was backdated"):
        run(parts)


def test_cannot_truncate_old_quote_population():
    parts = fixture()
    parts[-1] = []
    with pytest.raises(ValueError, match="truncated or rewritten"):
        run(parts)


@pytest.mark.parametrize("field,value", [
    ("bid", "99"), ("ask", "102.5"), ("available_contracts", 1),
    ("quote_id", "q1_modified"), ("received_at_ms", 151),
])
def test_cannot_rewrite_prior_quote(field, value):
    parts = fixture()
    parts[-1][0][field] = value
    with pytest.raises(ValueError):
        run(parts)


def test_late_backfill_with_earlier_receive_time_rejected():
    parts = fixture()
    parts[2] = []
    with pytest.raises(ValueError, match="Newly disclosed quote was available"):
        run(parts)


def test_same_or_reverse_cutoff_rejected():
    for cutoff in (155, 154):
        parts = fixture()
        parts[3]["as_of_ms"] = cutoff
        parts[-1] = parts[-1][:1]
        with pytest.raises(ValueError, match="strictly advance"):
            run(parts)


def test_invalid_tape_digest_rejected():
    with pytest.raises(ValueError, match="digest mismatch"):
        run(fixture(), prior_hash="0" * 64)
    with pytest.raises(ValueError, match="digest mismatch"):
        run(fixture(), later_hash="0" * 64)


def test_randomized_append_only_quantity_and_cost_invariants():
    rng = random.Random(31051)
    for _ in range(250):
        parts = fixture()
        requested = rng.randint(1, 15)
        parts[1]["requested_contracts"] = requested
        parts[4]["requested_contracts"] = requested
        parts[2][0]["available_contracts"] = rng.randint(0, 15)
        parts[-1][0]["available_contracts"] = parts[2][0]["available_contracts"]
        parts[-1][1]["available_contracts"] = rng.randint(0, 15)
        report = run(parts)
        assert 0 <= report["earlier_hypothetical_filled_contracts"] <= report["later_hypothetical_filled_contracts"] <= requested
        assert report["new_hypothetical_filled_contracts"] == (report["later_hypothetical_filled_contracts"] - report["earlier_hypothetical_filled_contracts"])
