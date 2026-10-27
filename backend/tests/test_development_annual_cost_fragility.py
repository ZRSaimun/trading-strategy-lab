"""Synthetic-only tests; no market archives, broker connection or profit claims."""
import copy
from datetime import datetime, timezone
import pytest

from app.development_annual_cost_fragility import (
    _fingerprint, audit_development_annual_cost_fragility as audit,
)


def t(year, month=1, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def fixture():
    manifest = {
        "source": {"provider": "synthetic", "venue": "OFFLINE", "instrument": "XAUUSD-CFD", "quote_side": "BID", "timezone": "UTC", "account_alias": "research", "settlement_currency": "GBP", "archive_sha256": "a" * 64},
        "partition": {"registered_at": t(2017), "development_end": t(2026), "validation_start": t(2026, 6), "holdout_start": t(2027), "embargo_seconds": 86400},
        "candidates": ["A", "B"],
        "folds": [{"fold_id": f"fold-{y}", "year": y, "train_start": t(y-1), "train_end": t(y, 1, 1), "test_start": t(y, 2, 1), "test_end": t(y, 3, 1), "train_label_available_at": t(y, 1, 1), "test_label_available_at": t(y, 3, 1) + 1} for y in range(2019, 2026)],
    }
    trials = []
    for ci, cid in enumerate(manifest["candidates"]):
        for fi, fold in enumerate(manifest["folds"]):
            trials.append({"candidate_id": cid, "fold_id": fold["fold_id"], "source_sha256": "a"*64,
                           "gross_cash": "10.00" if ci == 0 else "11.00", "spread_cash": "1.00", "slippage_cash": "0.50", "commission_cash": "0.25", "financing_cash": "-0.50", "fx_cash": "0.25",
                           "observed_at": fold["test_end"] + 2, "receipt_sha256": f"{ci*len(manifest['folds'])+fi+1:064x}"})
    return manifest, trials


def run(m=None, rows=None, multiplier="2"):
    if m is None or rows is None:
        base_m, base_rows = fixture()
        m = base_m if m is None else m
        rows = base_rows if rows is None else rows
    return audit(m, rows, _fingerprint(m), adverse_multiplier=multiplier)


def test_seven_year_complete_population_costs_drawdown_and_flags():
    report = run()
    assert report["year_count"] == 7 and report["fold_count"] == 7
    assert report["candidate_summaries"]["A"]["baseline_net_cash"] == "59.50"
    assert report["candidate_summaries"]["A"]["adverse_net_cash"] == "42.00"
    assert report["baseline_development_winner"] == "B"
    assert report["winner_changes_with_year_removal"] is False
    assert report["candidate_summaries"]["A"]["max_chronological_drawdown_cash"] == "0.00"
    assert not any(report[k] for k in ("source_authenticated", "pre_outcome_registration_verified", "independent_holdout_verified", "real_costs_verified", "verified_profitability", "may_execute_demo_order", "may_execute_real_order"))


def test_financing_credit_removed_under_stress():
    m, rows = fixture()
    rows[0]["financing_cash"] = "-5.00"
    report = run(m, rows)
    assert report["candidate_summaries"]["A"]["baseline_net_cash"] == "64.00"
    assert report["candidate_summaries"]["A"]["adverse_net_cash"] == "42.00"


def test_positive_financing_debit_is_stressed():
    m, rows = fixture()
    rows[0]["financing_cash"] = "2.00"
    report = run(m, rows)
    assert report["candidate_summaries"]["A"]["baseline_net_cash"] == "57.00"
    assert report["candidate_summaries"]["A"]["adverse_net_cash"] == "38.00"


def test_downside_and_year_removal_detect_unstable_winner():
    m, rows = fixture()
    for row in rows:
        if row["candidate_id"] == "A" and row["fold_id"] == "fold-2025":
            row["gross_cash"] = "100.00"
        if row["candidate_id"] == "B" and row["fold_id"] == "fold-2025":
            row["gross_cash"] = "-50.00"
    report = run(m, rows)
    assert report["baseline_development_winner"] == "A"
    assert report["leave_one_year_out_winners"]["2025"] == "B"
    assert report["winner_changes_with_year_removal"]
    assert report["candidate_summaries"]["B"]["max_chronological_drawdown_cash"] == "51.50"


def test_reorder_trials_does_not_change_report_or_mutate():
    m, rows = fixture()
    before = copy.deepcopy(rows)
    assert run(m, rows) == run(m, list(reversed(rows)))
    assert rows == before


def test_receipt_digest_changes_on_amount_or_clock_change():
    m, rows = fixture()
    old = run(m, rows)["post_outcome_receipts_sha256"]
    for field, value in (("gross_cash", "11.50"), ("observed_at", rows[0]["observed_at"] + 1)):
        changed = copy.deepcopy(rows)
        changed[0][field] = value
        assert run(m, changed)["post_outcome_receipts_sha256"] != old


def test_manifest_digest_mismatch_rejected():
    m, rows = fixture()
    with pytest.raises(ValueError, match="digest mismatch"):
        audit(m, rows, "b"*64)


@pytest.mark.parametrize("field,value", [
    ("gross_cash", "NaN"), ("gross_cash", "1e6"), ("gross_cash", "1000000000"),
    ("gross_cash", "1.001"), ("gross_cash", "-0.00"),
    ("spread_cash", "-0.01"), ("slippage_cash", "-1.00"),
    ("commission_cash", "Infinity"), ("fx_cash", "0.001"),
    ("financing_cash", "-0"), ("financing_cash", "abc"),
    ("observed_at", True), ("observed_at", 1),
    ("receipt_sha256", "A"*64), ("source_sha256", "b"*64),
    ("candidate_id", "foreign"), ("fold_id", "unknown"),
])
def test_invalid_trial_fail_closed(field, value):
    m, rows = fixture()
    rows[0][field] = value
    with pytest.raises(ValueError):
        run(m, rows)


@pytest.mark.parametrize("change", [
    lambda m: m["source"].update(provider="Other/Bad"),
    lambda m: m["source"].update(quote_side="UNKNOWN"),
    lambda m: m["source"].update(timezone="Europe/London"),
    lambda m: m["source"].update(archive_sha256="A"*64),
    lambda m: m["source"].update(settlement_currency="US"),
    lambda m: m["partition"].update(holdout_start=t(2025)),
    lambda m: m["partition"].update(validation_start=t(2025)),
    lambda m: m["partition"].update(embargo_seconds=0),
    lambda m: m["partition"].update(registered_at=t(2020)),
    lambda m: m["folds"][0].update(test_start=t(2019, 1, 1)),
    lambda m: m["folds"][0].update(test_end=t(2027)),
    lambda m: m["folds"][0].update(year=2020),
    lambda m: m["folds"][0].update(train_label_available_at=t(2019, 1, 2)),
    lambda m: m["folds"][0].update(test_label_available_at=t(2026, 7)),
    lambda m: m["folds"][1].update(fold_id="fold-2019"),
    lambda m: m.update(candidates=["B", "A"]),
    lambda m: m.update(candidates=["A", "A"]),
    lambda m: m.update(extra=True),
    lambda m: m["folds"].__delitem__(slice(0,5)),
])
def test_invalid_manifest_fail_closed(change):
    m, rows = fixture()
    change(m)
    with pytest.raises(ValueError):
        run(m, rows)


@pytest.mark.parametrize("multiplier", ["0.99", "11", "NaN", "1e1", "01", "-1", "2.001", "", 2, True])
def test_invalid_multiplier_rejected(multiplier):
    m, rows = fixture()
    with pytest.raises(ValueError):
        run(m, rows, multiplier)


def test_missing_duplicate_extra_trials_rejected():
    m, rows = fixture()
    for bad in (rows[:-1], rows + [rows[0]], [rows[0], *rows[1:-1], rows[0]]):
        with pytest.raises(ValueError):
            run(m, bad)


def test_duplicate_receipt_hash_rejected_even_for_other_candidate():
    m, rows = fixture()
    rows[1]["receipt_sha256"] = rows[0]["receipt_sha256"]
    with pytest.raises(ValueError, match="receipt"):
        run(m, rows)


def test_adverse_multiplier_one_is_still_conservative_due_to_credit_removal():
    report = run(multiplier="1")
    assert report["candidate_summaries"]["A"]["adverse_net_cash"] == "56.00"


def test_explicit_zero_costs_not_treated_as_broker_evidence():
    m, rows = fixture()
    for row in rows:
        for key in ("spread_cash", "slippage_cash", "commission_cash", "fx_cash", "financing_cash"):
            row[key] = "0.00"
    report = run(m, rows)
    assert report["candidate_summaries"]["A"]["baseline_net_cash"] == "70.00"
    assert report["real_costs_verified"] is False


def test_missing_cost_component_and_holdout_outcome_field_rejected():
    m, rows = fixture()
    for key in ("spread_cash", "slippage_cash", "commission_cash", "fx_cash", "financing_cash"):
        changed = copy.deepcopy(rows)
        del changed[0][key]
        with pytest.raises(ValueError, match="schema"):
            run(m, changed)
    rows[0]["holdout_net_cash"] = "1000000.00"
    with pytest.raises(ValueError, match="schema"):
        run(m, rows)


def test_randomized_adverse_monotonicity_and_complete_census_250():
    """Seeded synthetic property tests; not historical observations."""
    import random
    rng = random.Random(20261027)
    for _ in range(250):
        m, rows = fixture()
        for row in rows:
            row["gross_cash"] = f"{rng.randint(-10000, 10000)/100:.2f}"
            for key in ("spread_cash", "slippage_cash", "commission_cash", "fx_cash"):
                row[key] = f"{rng.randint(0, 500)/100:.2f}"
            row["financing_cash"] = f"{rng.randint(-1000, 1000)/100:.2f}"
        report = run(m, rows, multiplier=str(rng.randint(1, 10)))
        assert report["fold_count"] == len(m["folds"])
        for candidate in m["candidates"]:
            from decimal import Decimal
            summary = report["candidate_summaries"][candidate]
            assert Decimal(summary["adverse_net_cash"]) <= Decimal(summary["baseline_net_cash"])
            assert Decimal(summary["max_chronological_drawdown_cash"]) >= 0


def test_test_label_must_be_available_before_trial_receipt():
    m, rows = fixture()
    rows[0]["observed_at"] = m["folds"][0]["test_end"]
    with pytest.raises(ValueError, match="receipt"):
        run(m, rows)
