"""Synthetic-only financing reconciliation regressions, no broker observations."""
import copy
import random

import pytest

from app.declared_cfd_financing_cash_reconcile import audit_declared_financing_cash


def fixture(n=3):
    scope = dict(provider="Synthetic", venue="DEMO", account_alias="a1",
                 instrument="XAUUSD-CFD", position_side="LONG", settlement_currency="GBP",
                 position_id="p1", opened_at_utc=1000, closed_at_utc=10000,
                 as_of_utc=20000, calendar_sha256="a" * 64)
    due = [2000 + i * 1000 for i in range(n)]
    amounts = ["-1.25", "0.75", "-0.50"][:n]
    events = [dict(event_id=f"e{i}", position_id="p1", account_alias="a1",
                   instrument="XAUUSD-CFD", settlement_currency="GBP",
                   rollover_at_utc=t, booked_at_utc=t + 5, observed_at_utc=t + 10,
                   amount=amounts[i], source_sha256="b" * 64)
              for i, t in enumerate(due)]
    cash = [dict(cash_id=f"c{i}", event_id=f"e{i}", position_id="p1",
                 account_alias="a1", settlement_currency="GBP",
                 posted_at_utc=t + 20, observed_at_utc=t + 30,
                 amount=amounts[i], source_sha256="c" * 64)
            for i, t in enumerate(due)]
    return scope, due, events, cash


def run(data=None):
    return audit_declared_financing_cash(*(fixture() if data is None else data))


def test_signed_cash_debits_credits_and_exact_decimal():
    r = run()
    assert r["declared_net_cash_delta"] == "-1.00"
    assert r["declared_net_financing_cost"] == "1.00"
    assert r["declared_rollover_count"] == 3
    assert r["broker_source_authenticated"] is False
    assert r["cash_ledger_independently_verified"] is False
    assert r["may_execute_real_order"] is False


def test_zero_rollovers_does_not_prove_free_financing():
    scope, _, _, _ = fixture()
    r = run((scope, [], [], []))
    assert r["status"] == "NO_DUE_ROLLOVERS_UNVERIFIED"
    assert r["declared_net_cash_delta"] == "0"


def test_input_immutable_fingerprint_stable_and_mutation_sensitive():
    data = fixture()
    before = copy.deepcopy(data)
    a = run(data)
    assert data == before
    assert run(data) == a
    changed = copy.deepcopy(data)
    changed[3][0]["source_sha256"] = "d" * 64
    assert run(changed)["declared_evidence_sha256"] != a["declared_evidence_sha256"]


def test_late_bookings_and_postings_are_counted_not_silently_backdated():
    scope, due, events, cash = fixture()
    scope["closed_at_utc"] = 4001
    events[2]["booked_at_utc"] = 10001
    events[2]["observed_at_utc"] = 10002
    cash[2]["posted_at_utc"] = 10003
    cash[2]["observed_at_utc"] = 10004
    r = run((scope, due, events, cash))
    assert r["events_booked_after_close"] == 1
    assert r["cash_postings_after_close"] == 1


@pytest.mark.parametrize("mutation", [
    lambda d: d[1].reverse(),
    lambda d: d[1].__setitem__(1, d[1][0]),
    lambda d: d[1].append(5000),
    lambda d: d[1].__setitem__(0, True),
    lambda d: d[1].__setitem__(0, 999),
    lambda d: d[1].__setitem__(0, 10000),
    lambda d: d[2].pop(),
    lambda d: d[3].pop(),
    lambda d: d[2].append(copy.deepcopy(d[2][0])),
    lambda d: d[3].append(copy.deepcopy(d[3][0])),
    lambda d: d[2][0].update(event_id="e1"),
    lambda d: d[3][0].update(cash_id="c1"),
    lambda d: d[3][0].update(event_id="e1"),
    lambda d: d[2][0].update(rollover_at_utc=3000),
    lambda d: d[2].reverse(),
    lambda d: d[2][0].update(account_alias="other"),
    lambda d: d[3][0].update(account_alias="other"),
    lambda d: d[2][0].update(position_id="other"),
    lambda d: d[3][0].update(position_id="other"),
    lambda d: d[2][0].update(instrument="WTIUSD-CFD"),
    lambda d: d[2][0].update(settlement_currency="USD"),
    lambda d: d[3][0].update(settlement_currency="USD"),
    lambda d: d[2][0].update(source_sha256="not-a-sha"),
    lambda d: d[3][0].update(source_sha256="not-a-sha"),
    lambda d: d[2][0].update(booked_at_utc=1999),
    lambda d: d[2][0].update(observed_at_utc=2001),
    lambda d: d[3][0].update(posted_at_utc=2000),
    lambda d: d[3][0].update(observed_at_utc=2001),
    lambda d: d[2][0].update(booked_at_utc=20001),
    lambda d: d[3][0].update(posted_at_utc=20001),
    lambda d: d[2][0].update(amount="-1.26"),
    lambda d: d[3][0].update(amount="-1.26"),
    lambda d: d[2][0].update(amount="NaN"),
    lambda d: d[2][0].update(amount="1e3"),
    lambda d: d[2][0].update(amount="-0"),
    lambda d: d[2][0].update(amount="0.00"),
    lambda d: d[3][0].update(amount="-0.00"),
    lambda d: d[2][0].update(amount=1.25),
    lambda d: d[3][0].update(amount=True),
    lambda d: d[2][0].update(amount="9999999999"),
    lambda d: d[2][0].update(amount="1.000000000"),
    lambda d: d[2][0].update(extra="secret"),
    lambda d: d[3][0].update(extra="secret"),
    lambda d: d[0].update(extra="secret"),
    lambda d: d[0].update(position_side="BUY"),
    lambda d: d[0].update(settlement_currency="GB"),
    lambda d: d[0].update(calendar_sha256="not-a-sha"),
    lambda d: d[0].update(opened_at_utc=True),
    lambda d: d[0].update(closed_at_utc=1000),
    lambda d: d[0].update(as_of_utc=9999),
])
def test_malformed_or_unreconciled_declarations_fail_closed(mutation):
    data = list(copy.deepcopy(fixture()))
    mutation(data)
    with pytest.raises(ValueError):
        run(data)


def test_seeded_multi_year_synthetic_population():
    rng = random.Random(20261027)
    scope, _, _, _ = fixture()
    scope.update(opened_at_utc=1000, closed_at_utc=200_000_000,
                 as_of_utc=201_000_000)
    due = [2000 + i * 86400 for i in range(1000)]
    events, cash = [], []
    total = 0
    for i, t in enumerate(due):
        cents = rng.choice([*range(-500, 0), *range(1, 501)])
        total += cents
        amount = f"{cents / 100:.2f}"
        events.append(dict(event_id=f"e{i}", position_id="p1", account_alias="a1",
                           instrument="XAUUSD-CFD", settlement_currency="GBP",
                           rollover_at_utc=t, booked_at_utc=t + 5,
                           observed_at_utc=t + 10, amount=amount,
                           source_sha256="b" * 64))
        cash.append(dict(cash_id=f"c{i}", event_id=f"e{i}", position_id="p1",
                         account_alias="a1", settlement_currency="GBP",
                         posted_at_utc=t + 20, observed_at_utc=t + 30,
                         amount=amount, source_sha256="c" * 64))
    r = run((scope, due, events, cash))
    assert r["declared_rollover_count"] == 1000
    assert r["declared_net_cash_delta"] == f"{total / 100:.2f}"
    assert r["untouched_holdout_or_profit_verified"] is False
    cash[499]["amount"] = "999.99"
    with pytest.raises(ValueError, match="Cash amount"):
        run((scope, due, events, cash))
