"""Synthetic-only offline normalized export continuity tests."""
from copy import deepcopy
from decimal import Decimal
import random

import pytest

from app.broker_export_snapshot_continuity import audit_broker_export_snapshot_continuity

SRC = {"provider": "synthetic", "venue": "synthetic", "account_alias": "demo-1", "settlement_currency": "GBP"}


def event(name, *, kind="FINANCING", occurred=110, recorded=115, cash="1.25", qty="0", side="NONE", revision=1, supersedes=None):
    return dict(event_id=name, kind=kind, instrument="XAUUSD-CFD", position_id="p1",
                side=side, occurred_at=occurred, recorded_at=recorded,
                quantity=qty, cash_amount=cash, revision=revision,
                supersedes_id=supersedes, evidence_sha256="e" * 64)


def snapshot(name, *, end=200, exported=220, ingested=230, events=None, sha="a"):
    return dict(source=deepcopy(SRC), snapshot_id=name, statement_sha256=sha * 64,
                coverage_start=100, coverage_end=end, exported_at=exported,
                ingested_at=ingested, events=deepcopy(events or []))


def pair():
    old = snapshot("s1", events=[event("f1")])
    new = snapshot("s2", end=300, exported=330, ingested=340,
                   events=[event("f1"), event("f2", occurred=260, recorded=270, cash="0.75")], sha="b")
    return old, new


def audit(a=None, b=None):
    if a is None:
        a, b = pair()
    return audit_broker_export_snapshot_continuity(a, b)


def test_append_only_cash_totals_are_exact_and_not_profit():
    result = audit()
    assert result["status"] == "DECLARED_APPEND_ONLY_CONTINUITY"
    assert (result["earlier_event_count"], result["later_event_count"], result["new_event_count"]) == (1, 2, 1)
    assert result["earlier_effective_cash_charges"]["FINANCING"] == "1.25"
    assert result["later_effective_cash_charges"]["FINANCING"] == "2.00"
    assert result["source_authenticated"] is result["verified_profitability"] is result["may_execute_order"] is False


def test_order_independent_declaration_digests_and_no_input_mutation():
    a, b = pair()
    original = deepcopy((a, b))
    first = audit(a, b)
    b["events"].reverse()
    second = audit(a, b)
    assert first == second
    assert a == original[0]


def test_late_historical_fee_is_retained_and_withholds_completeness():
    a, b = pair()
    b["events"].append(event("late", kind="COMMISSION", occurred=150, recorded=250, cash="3.50"))
    report = audit(a, b)
    assert report["status"] == "WITHHELD_LATE_HISTORICAL_POSTINGS"
    assert report["late_historical_event_ids"] == ["late"]
    assert report["later_effective_cash_charges"]["COMMISSION"] == "3.50"


def test_correction_is_append_only_and_supersedes_cash():
    a, b = pair()
    b["events"].append(event("f1-rev2", occurred=110, recorded=255, cash="2.50", revision=2, supersedes="f1"))
    report = audit(a, b)
    assert report["new_correction_ids"] == ["f1-rev2"]
    assert report["late_historical_event_ids"] == ["f1-rev2"]
    assert report["earlier_effective_cash_charges"]["FINANCING"] == "1.25"
    assert report["later_effective_cash_charges"]["FINANCING"] == "3.25"


@pytest.mark.parametrize("change", [
    lambda a,b: b["events"].pop(0),
    lambda a,b: b["events"][0].update(cash_amount="9.99"),
    lambda a,b: b["events"].append(deepcopy(b["events"][0])),
    lambda a,b: b["source"].update(provider="other"),
    lambda a,b: b.update(coverage_start=101),
    lambda a,b: b.update(coverage_end=199),
    lambda a,b: b.update(exported_at=220),
    lambda a,b: b.update(ingested_at=229),
    lambda a,b: b.update(snapshot_id="s1"),
    lambda a,b: b.update(statement_sha256=a["statement_sha256"]),
    lambda a,b: b["events"].append(event("backfill", occurred=150, recorded=200)),
    lambda a,b: b["events"][1].update(recorded_at=331),
    lambda a,b: b["events"][1].update(occurred_at=331),
    lambda a,b: b["events"][1].update(occurred_at=90),
    lambda a,b: b["events"][1].update(revision=2),
    lambda a,b: b["events"][1].update(supersedes_id="absent", revision=2),
    lambda a,b: b["events"][1].update(kind="FILL"),
    lambda a,b: b["events"][1].update(quantity="-1"),
    lambda a,b: b["events"][1].update(cash_amount="NaN"),
    lambda a,b: b["events"][1].update(cash_amount="-0.00"),
    lambda a,b: b["events"][1].update(evidence_sha256="z"*64),
    lambda a,b: b["events"][1].update(revision=True),
    lambda a,b: b["events"][1].update(recorded_at=True),
    lambda a,b: b["events"][1].update(side="BUY"),
    lambda a,b: b["events"][1].update(unexpected=True),
    lambda a,b: b.update(unexpected=True),
    lambda a,b: b["source"].update(unexpected=True),
])
def test_invalid_mutations_fail_closed(change):
    a, b = pair()
    change(a, b)
    with pytest.raises(ValueError):
        audit(a, b)


def test_cash_only_and_fill_fields_are_separate():
    a, b = pair()
    fill = event("buy", kind="FILL", occurred=260, recorded=270, qty="2.5", cash="0", side="BUY")
    b["events"].append(fill)
    report = audit(a, b)
    assert report["later_effective_cash_charges"]["FINANCING"] == "2.00"
    assert report["new_event_count"] == 2
    b["events"][-1]["cash_amount"] = "2.00"
    with pytest.raises(ValueError):
        audit(a, b)


def test_correction_cannot_fork_or_change_identity():
    a, b = pair()
    b["events"].append(event("r2", occurred=110, recorded=255, cash="2.50", revision=2, supersedes="f1"))
    b["events"].append(event("r2b", occurred=110, recorded=256, cash="3.50", revision=2, supersedes="f1"))
    with pytest.raises(ValueError):
        audit(a, b)
    b["events"].pop()
    b["events"][-1]["instrument"] = "WTIUSD-CFD"
    with pytest.raises(ValueError):
        audit(a, b)


def test_multi_year_2018_2026_causal_append_and_randomized_exact_cash():
    rng = random.Random(20261026)
    year = 365 * 86400
    start = 1514764800  # 2018-01-01 UTC
    old = snapshot("2018-export", end=start + 30, exported=start + 40,
                   ingested=start + 41, events=[], sha="a")
    old["coverage_start"] = start
    rows = []
    expected = Decimal(0)
    for i in range(201):
        at = start + 40 + i * (9 * year // 202)
        cash = Decimal(rng.randrange(-5000, 5001)) / 100
        rows.append(event(f"evt-{i}", occurred=at, recorded=at + 1, cash=f"{cash:.2f}"))
        expected += cash
    later = snapshot("2026-export", end=start + 9 * year,
                     exported=start + 9 * year + 10, ingested=start + 9 * year + 20,
                     events=rows, sha="b")
    later["coverage_start"] = start
    report = audit(old, later)
    assert report["new_event_count"] == 201
    assert Decimal(report["later_effective_cash_charges"]["FINANCING"]) == expected
    assert report["late_historical_event_ids"] == []


def test_bounded_population_and_snapshot_clocks():
    a, b = pair()
    b["events"] = [event(f"e{i}", occurred=250, recorded=260) for i in range(5001)]
    with pytest.raises(ValueError):
        audit(a, b)
    a, b = pair()
    a["coverage_end"] = a["exported_at"] + 1
    with pytest.raises(ValueError):
        audit(a, b)
