"""Synthetic-only regression tests; no real brokerage calendar or cash evidence."""
import copy
from datetime import date, datetime, timedelta, timezone
import random
from zoneinfo import ZoneInfo

import pytest

from app.declared_cfd_rollover_calendar import (
    audit_declared_rollover_calendar, fingerprint_declared_rollover_calendar,
)

UTC = timezone.utc


def epoch(value):
    return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())


def fixture(*, opened="2026-10-23T00:00:00Z", closed="2026-10-27T23:00:00Z",
            cutoff="01:30", zone="Europe/London", late=False):
    s = dict(provider="Synthetic", venue="DEMO", account_alias="paper1",
             instrument="XAUUSD-CFD", position_side="LONG", settlement_currency="GBP",
             timezone=zone, local_cutoff=cutoff, opened_at_utc=epoch(opened),
             closed_at_utc=epoch(closed), registered_at_utc=epoch("2026-10-28T12:00:00Z"),
             as_of_utc=epoch("2026-10-29T12:00:00Z"), calendar_source_sha256="a" * 64)
    z = ZoneInfo(zone)
    first = datetime.fromtimestamp(s["opened_at_utc"], UTC).astimezone(z).date()
    last = datetime.fromtimestamp(s["closed_at_utc"], UTC).astimezone(z).date()
    days = []
    for i in range((last - first).days + 1):
        day = first + timedelta(days=i)
        fold = 1 if day == date(2026, 10, 25) and cutoff == "01:30" and zone == "Europe/London" else 0
        h, m = map(int, cutoff.split(":"))
        local = datetime(day.year, day.month, day.day, h, m, tzinfo=z, fold=fold)
        t = int(local.timestamp())
        charge = day.weekday() < 5
        days.append(dict(local_date=day.isoformat(), cutoff_at_utc=t, fold=fold,
                         offset_minutes=int(local.utcoffset().total_seconds() / 60),
                         kind="CHARGE" if charge else "NO_CHARGE",
                         multiplier=3 if charge and day.weekday() == 2 else 1 if charge else 0,
                         reason="BROKER_ROLLOVER" if charge else "MARKET_CLOSED",
                         evidence_sha256=f"{i+1:064x}", published_at_utc=t-200,
                         ingested_at_utc=t+100 if late and i == 0 else t-100))
    return s, days


def run(s=None, days=None, digest=None, expected=None):
    if s is None:
        s, original = fixture()
        if days is None:
            days = original
    if days is None:
        _, days = fixture()
    if expected is None:
        expected = [r["cutoff_at_utc"] for r in days if r["kind"] == "CHARGE" and
                    s["opened_at_utc"] <= r["cutoff_at_utc"] < s["closed_at_utc"]]
    return audit_declared_rollover_calendar(
        s, days, fingerprint_declared_rollover_calendar(s, days) if digest is None else digest, expected)


def test_complete_declared_calendar_and_dst_fall_back():
    s, days = fixture()
    report = run(s, days)
    assert report["status"] == "PRE_CUTOFF_DECLARATIONS_ONLY"
    assert report["calendar_days"] == 5
    assert len(report["declared_due_rollovers"]) == 3
    assert report["declared_total_multiplier"] == 3
    assert days[2]["fold"] == 1 and days[2]["offset_minutes"] == 0
    assert report["source_authenticated"] is False
    assert report["may_execute_real_order"] is False
    assert report["rates_or_cash_charges_verified"] is False


def test_late_evidence_is_not_causal_proof():
    s, days = fixture(late=True)
    r = run(s, days)
    assert r["status"] == "RETROSPECTIVE_DECLARATIONS_ONLY"
    assert r["late_evidence_dates"] == ["2026-10-23"]
    assert r["late_evidence_count"] == 1


def test_late_calendar_day_outside_position_still_forces_retrospective_status():
    s, days = fixture(late=True)
    # The first calendar cutoff is 00:30Z, before this position opens.
    s["opened_at_utc"] = epoch("2026-10-23T02:00:00Z")
    r = run(s, days)
    assert r["status"] == "RETROSPECTIVE_DECLARATIONS_ONLY"
    assert r["late_evidence_dates"] == ["2026-10-23"]
    assert r["late_evidence_count"] == 1
    assert len(r["declared_due_rollovers"]) == 2


def test_pre_cutoff_evidence_is_not_automatically_available_at_entry():
    s, days = fixture()
    r = run(s, days)
    assert r["status"] == "PRE_CUTOFF_DECLARATIONS_ONLY"
    assert r["all_due_charge_declarations_ingested_by_position_open"] is False
    assert r["due_charge_declarations_unavailable_at_open_count"] == 3
    assert r["due_charge_declarations_unavailable_at_open_dates"] == [
        "2026-10-23", "2026-10-26", "2026-10-27"
    ]


def test_all_due_charge_declarations_can_be_declared_available_before_entry():
    s, days = fixture()
    for row in days:
        row["published_at_utc"] = epoch("2026-10-22T00:00:00Z")
        row["ingested_at_utc"] = epoch("2026-10-22T00:01:00Z")
    r = run(s, days)
    assert r["all_due_charge_declarations_ingested_by_position_open"] is True
    assert r["due_charge_declarations_unavailable_at_open_count"] == 0
    assert r["source_authenticated"] is False
    assert r["decision_time_registration_verified"] is False


def test_zero_due_charges_never_proves_entry_time_cost_schedule():
    s, days = fixture()
    for row in days:
        row.update(kind="NO_CHARGE", multiplier=0, reason="BROKER_WAIVER")
    r = run(s, days, expected=[])
    assert r["all_due_charge_declarations_ingested_by_position_open"] is False
    assert r["due_charge_declarations_unavailable_at_open_count"] == 0
    assert r["rates_or_cash_charges_verified"] is False


def test_empty_charge_population_does_not_prove_free_financing():
    s, days = fixture()
    for row in days:
        row.update(kind="NO_CHARGE", multiplier=0, reason="BROKER_WAIVER")
    r = run(s, days, expected=[])
    assert r["status"] == "NO_DECLARED_DUE_ROLLOVERS_UNVERIFIED"
    assert r["declared_due_rollovers"] == []


def test_open_and_close_boundaries_do_not_charge_outside_position():
    s, days = fixture()
    s["opened_at_utc"] = epoch("2026-10-23T02:00:00Z")
    s["closed_at_utc"] = epoch("2026-10-27T01:00:00Z")
    r = run(s, days)
    assert len(r["declared_due_rollovers"]) == 1  # Monday only


def test_digest_is_stable_and_mutation_changes_fingerprint():
    s, days = fixture()
    before = copy.deepcopy((s, days))
    a = run(s, days)
    assert (s, days) == before
    assert a == run(s, days)
    changed = copy.deepcopy(days)
    changed[0]["evidence_sha256"] = "b" * 64
    assert run(s, changed)["calendar_sha256"] != a["calendar_sha256"]
    with pytest.raises(ValueError, match="fingerprint"):
        run(s, changed, digest=a["calendar_sha256"])


@pytest.mark.parametrize("mutator", [
    lambda x: x.pop(1),
    lambda x: x.append(copy.deepcopy(x[-1])),
    lambda x: x.__setitem__(1, copy.deepcopy(x[0])),
    lambda x: x.reverse(),
    lambda x: x[0].update(local_date="2026-02-30"),
    lambda x: x[0].update(local_date="bad"),
    lambda x: x[0].update(cutoff_at_utc=x[0]["cutoff_at_utc"]+3600),
    lambda x: x[0].update(offset_minutes=0),
    lambda x: x[0].update(fold=1),
    lambda x: x[2].update(fold=0),
    lambda x: x[0].update(fold=True),
    lambda x: x[0].update(offset_minutes=True),
    lambda x: x[0].update(cutoff_at_utc=True),
    lambda x: x[0].update(multiplier=True),
    lambda x: x[0].update(multiplier=8),
    lambda x: x[0].update(multiplier=0),
    lambda x: x[0].update(reason="HOLIDAY"),
    lambda x: x[1].update(multiplier=1),
    lambda x: x[1].update(reason="BROKER_ROLLOVER"),
    lambda x: x[1].update(kind="UNKNOWN"),
    lambda x: x[0].update(evidence_sha256="bad"),
    lambda x: x[0].update(published_at_utc=x[0]["ingested_at_utc"]+1),
    lambda x: x[0].update(ingested_at_utc=epoch("2026-10-29T00:00:00Z")),
    lambda x: x[0].update(extra="outcome"),
])
def test_invalid_calendar_census_and_evidence_fail_closed(mutator):
    s, days = fixture()
    mutator(days)
    with pytest.raises(ValueError):
        run(s, days)


@pytest.mark.parametrize("key,value", [
    ("provider", "Bad provider"), ("venue", ""), ("position_side", "BUY"),
    ("position_side", []), ("settlement_currency", "GB"), ("timezone", "Not/AZone"),
    ("timezone", "../etc/passwd"), ("local_cutoff", "24:00"),
    ("opened_at_utc", True), ("closed_at_utc", 0),
    ("registered_at_utc", 1), ("as_of_utc", 1),
    ("calendar_source_sha256", "BAD"),
])
def test_invalid_scope_fails_closed(key, value):
    s, days = fixture()
    s[key] = value
    with pytest.raises(ValueError):
        run(s, days)


def test_wrong_expected_rollover_census_fails():
    s, days = fixture()
    correct = run(s, days)["declared_due_rollovers"]
    for wrong in ([], correct[:-1], correct + correct[-1:], list(reversed(correct)), [True], [correct[0]+1, *correct[1:]]):
        with pytest.raises(ValueError, match="population mismatch"):
            run(s, days, expected=wrong)


def test_dst_spring_forward_nonexistent_cutoff_rejected():
    s, days = fixture(opened="2026-03-28T12:00:00Z", closed="2026-03-30T20:00:00Z")
    s["registered_at_utc"] = epoch("2026-03-31T00:00:00Z")
    s["as_of_utc"] = epoch("2026-04-01T00:00:00Z")
    with pytest.raises(ValueError, match="Nonexistent"):
        run(s, days)


def test_eight_year_synthetic_coverage_and_missing_day():
    s = dict(provider="Synthetic", venue="DEMO", account_alias="a1", instrument="XAUUSD-CFD",
             position_side="SHORT", settlement_currency="GBP", timezone="America/New_York",
             local_cutoff="17:00", opened_at_utc=epoch("2019-01-02T00:00:00Z"),
             closed_at_utc=epoch("2026-10-28T00:00:00Z"),
             registered_at_utc=epoch("2026-10-29T00:00:00Z"),
             as_of_utc=epoch("2026-10-30T00:00:00Z"), calendar_source_sha256="c" * 64)
    z = ZoneInfo(s["timezone"])
    start = datetime.fromtimestamp(s["opened_at_utc"], UTC).astimezone(z).date()
    end = datetime.fromtimestamp(s["closed_at_utc"], UTC).astimezone(z).date()
    days = []
    for i in range((end-start).days+1):
        d = start + timedelta(days=i)
        local = datetime(d.year, d.month, d.day, 17, tzinfo=z)
        t = int(local.timestamp())
        charge = d.weekday() < 5
        days.append(dict(local_date=d.isoformat(), cutoff_at_utc=t, fold=0,
                         offset_minutes=int(local.utcoffset().total_seconds()/60),
                         kind="CHARGE" if charge else "NO_CHARGE",
                         multiplier=3 if charge and d.weekday() == 2 else 1 if charge else 0,
                         reason="BROKER_ROLLOVER" if charge else "MARKET_CLOSED",
                         evidence_sha256=f"{i+1:064x}", published_at_utc=t-200,
                         ingested_at_utc=t-100))
    r = run(s, days)
    assert r["distinct_calendar_years"] == 8
    assert r["at_least_three_calendar_years"] is True
    assert r["calendar_days"] > 2800
    assert len(r["declared_due_rollovers"]) > 1900
    with pytest.raises(ValueError, match="census"):
        run(s, days[:-1])
    assert r["verified_profitability"] is False


def test_seeded_multipliers_and_no_charge_are_exact_not_inferred():
    rng = random.Random(20261027)
    for _ in range(200):
        s, days = fixture()
        expected_sum = 0
        for row in days:
            if rng.randrange(3) == 0:
                row.update(kind="NO_CHARGE", multiplier=0, reason="BROKER_WAIVER")
            else:
                n = rng.randint(1, 7)
                row.update(kind="CHARGE", multiplier=n, reason="BROKER_ROLLOVER")
                expected_sum += n
        r = run(s, days)
        assert r["declared_total_multiplier"] == expected_sum
        assert r["rates_or_cash_charges_verified"] is False
