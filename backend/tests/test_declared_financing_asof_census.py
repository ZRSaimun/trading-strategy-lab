"""Synthetic-only tests for point-in-time financing availability; no broker calls."""
import copy
import random
import pytest

from app.declared_financing_asof_census import audit_declared_financing_asof


def fixture():
    scope = dict(provider="Synthetic", venue="DEMO", account_alias="a1",
                 instrument="XAUUSD-CFD", position_id="p1", settlement_currency="GBP",
                 opened_at_utc=1000, closed_at_utc=10000, as_of_utc=20000,
                 calendar_sha256="a" * 64)
    due = [2000, 3000, 4000]
    events = [dict(event_id=f"e{i}", rollover_at_utc=t, booked_at_utc=t + 5,
                   observed_at_utc=t + 10, amount=a, source_sha256="b" * 64,
                   provider="Synthetic", venue="DEMO", account_alias="a1",
                   instrument="XAUUSD-CFD", position_id="p1", settlement_currency="GBP")
              for i, (t, a) in enumerate(zip(due, ["-1.25", "0.75", "-0.50"]))]
    cash = [dict(cash_id=f"c{i}", event_id=f"e{i}", posted_at_utc=t + 20,
                 observed_at_utc=t + 30, amount=a, source_sha256="c" * 64,
                 provider="Synthetic", venue="DEMO", account_alias="a1",
                 instrument="XAUUSD-CFD", position_id="p1", settlement_currency="GBP")
            for i, (t, a) in enumerate(zip(due, ["-1.25", "0.75", "-0.50"]))]
    return scope, due, events, cash, [1999, 2000, 2029, 2030, 3029, 3030, 4030, 20000]


def run(data=None):
    return audit_declared_financing_asof(*(fixture() if data is None else data))


def test_unknown_never_becomes_zero_or_partial_total():
    r = run()
    s = r["snapshots"]
    assert s[0]["status"] == "NO_DUE_YET_UNVERIFIED" and s[0]["net_cash_delta"] is None
    assert s[1]["status"] == "INCOMPLETE_AS_OF" and s[1]["net_cash_delta"] is None
    assert s[2]["status"] == "INCOMPLETE_AS_OF" and s[2]["net_cash_delta"] is None
    assert s[3]["net_cash_delta"] == "-1.25"
    assert s[4]["net_cash_delta"] is None  # second rollover known, cash not observed
    assert s[5]["net_cash_delta"] == "-0.50"
    assert s[6]["net_cash_delta"] == "-1.00"
    assert s[7]["net_cash_delta"] == "-1.00"
    assert r["may_execute_real_order"] is False


def test_future_amount_changes_do_not_affect_earlier_cutoffs():
    original = fixture()
    before = copy.deepcopy(original)
    a = run(original)
    changed = copy.deepcopy(original)
    changed[2][2]["amount"] = "-999.99"
    changed[3][2]["amount"] = "-999.99"
    b = run(changed)
    assert a["snapshots"][:6] == b["snapshots"][:6]
    assert a["snapshots"][6] != b["snapshots"][6]
    assert original == before


def test_missing_cash_receipt_remains_unknown_after_audit():
    data = list(fixture())
    data[3].pop(1)
    s = run(data)["snapshots"]
    assert s[-1]["status"] == "INCOMPLETE_AS_OF"
    assert s[-1]["unknown_count"] == 1
    assert s[-1]["net_cash_delta"] is None


def test_late_post_close_receipt_not_backdated():
    data = list(fixture())
    data[3][0]["posted_at_utc"] = 10001
    data[3][0]["observed_at_utc"] = 10002
    assert run(data)["snapshots"][3]["net_cash_delta"] is None
    assert run(data)["snapshots"][-1]["net_cash_delta"] == "-1.00"


@pytest.mark.parametrize("mutation", [
    lambda d: d[0].update(extra="leak"),
    lambda d: d[0].update(provider=""),
    lambda d: d[0].update(calendar_sha256="bad"),
    lambda d: d[0].update(settlement_currency="GB"),
    lambda d: d[0].update(opened_at_utc=True),
    lambda d: d[0].update(closed_at_utc=1000),
    lambda d: d[0].update(as_of_utc=9999),
    lambda d: d[1].reverse(),
    lambda d: d[1].__setitem__(0, True),
    lambda d: d[1].__setitem__(1, 2000),
    lambda d: d[1].append(10000),
    lambda d: d[4].reverse(),
    lambda d: d[4].__setitem__(0, True),
    lambda d: d[4].__setitem__(1, 1999),
    lambda d: d[4].append(20001),
    lambda d: d[2][0].update(event_id="e1"),
    lambda d: d[2][0].update(rollover_at_utc=3000),
    lambda d: d[2][0].update(rollover_at_utc=5000),
    lambda d: d[2][0].update(booked_at_utc=1999),
    lambda d: d[2][0].update(observed_at_utc=2001),
    lambda d: d[2][0].update(observed_at_utc=20001),
    lambda d: d[2][0].update(source_sha256="bad"),
    lambda d: d[2][0].update(amount="NaN"),
    lambda d: d[2][0].update(amount="1e3"),
    lambda d: d[2][0].update(amount="-0"),
    lambda d: d[2][0].update(amount="0"),
    lambda d: d[2][0].update(amount="9999999999"),
    lambda d: d[2][0].update(amount=1.0),
    lambda d: d[2][0].update(extra="leak"),
    lambda d: d[2][0].update(provider="Other"),
    lambda d: d[2][0].update(account_alias="a2"),
    lambda d: d[2][0].update(instrument="WTIUSD-CFD"),
    lambda d: d[2][0].update(position_id="p2"),
    lambda d: d[2][0].update(settlement_currency="USD"),
    lambda d: d[3][0].update(cash_id="c1"),
    lambda d: d[3][0].update(event_id="e1"),
    lambda d: d[3][0].update(event_id=[]),
    lambda d: d[3][0].update(event_id=True),
    lambda d: d[3][0].update(posted_at_utc=2000),
    lambda d: d[3][0].update(observed_at_utc=2001),
    lambda d: d[3][0].update(observed_at_utc=20001),
    lambda d: d[3][0].update(source_sha256="bad"),
    lambda d: d[3][0].update(amount="-1.26"),
    lambda d: d[3][0].update(extra="leak"),
    lambda d: d[3][0].update(venue="Other"),
    lambda d: d[3][0].update(account_alias="a2"),
    lambda d: d[3][0].update(instrument="WTIUSD-CFD"),
    lambda d: d[3][0].update(position_id="p2"),
    lambda d: d[3][0].update(settlement_currency="USD"),
])
def test_invalid_population_rejected(mutation):
    data = list(copy.deepcopy(fixture()))
    mutation(data)
    with pytest.raises(ValueError):
        run(data)


def test_randomized_multiyear_census_and_no_lookahead():
    rng = random.Random(20261027)
    scope, _, _, _, _ = fixture()
    scope.update(closed_at_utc=200_000_000, as_of_utc=201_000_000)
    due = [2000 + i * 86400 for i in range(1000)]
    events, cash = [], []
    for i, t in enumerate(due):
        cents = rng.choice([*range(-500, 0), *range(1, 501)])
        amount = f"{cents // 100}.{abs(cents) % 100:02d}" if cents >= 0 else f"-{abs(cents) // 100}.{abs(cents) % 100:02d}"
        events.append(dict(event_id=f"e{i}", rollover_at_utc=t,
                           booked_at_utc=t + 5, observed_at_utc=t + 10,
                           amount=amount, source_sha256="b" * 64,
                           provider="Synthetic", venue="DEMO", account_alias="a1",
                           instrument="XAUUSD-CFD", position_id="p1",
                           settlement_currency="GBP"))
        cash.append(dict(cash_id=f"c{i}", event_id=f"e{i}",
                         posted_at_utc=t + 20, observed_at_utc=t + 30,
                         amount=amount, source_sha256="c" * 64,
                         provider="Synthetic", venue="DEMO", account_alias="a1",
                         instrument="XAUUSD-CFD", position_id="p1",
                         settlement_currency="GBP"))
    cutoffs = [due[0] - 1, due[0], due[0] + 30, due[499] + 30, due[-1] + 30]
    result = audit_declared_financing_asof(scope, due, events, cash, cutoffs)
    assert result["snapshots"][0]["net_cash_delta"] is None
    assert result["snapshots"][1]["net_cash_delta"] is None
    assert result["snapshots"][2]["complete_count"] == 1
    assert result["snapshots"][3]["complete_count"] == 500
    assert result["snapshots"][4]["complete_count"] == 1000
    cash[499]["observed_at_utc"] += 1000
    result = audit_declared_financing_asof(scope, due, events, cash, cutoffs)
    assert result["snapshots"][3]["net_cash_delta"] is None
    assert result["snapshots"][4]["net_cash_delta"] is not None
