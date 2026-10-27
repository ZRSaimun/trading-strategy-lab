"""Synthetic-only holdout gate regression; no market or brokerage data."""
import copy
import random

import pytest

from app.declared_holdout_release_gate import (
    audit_declared_holdout_release,
    prepare_declared_holdout_census_sha256,
    prepare_declared_holdout_manifest_sha256,
)


def fixture(count=35):
    census = [dict(observation_id=f"o{i:04d}", row_sha256=f"{i + 1:064x}",
                   source_sha256="a" * 64, decision_at_utc=2100 + i * 100,
                   label_available_at_utc=2150 + i * 100)
              for i in range(count)]
    manifest = dict(study_id="study-1", candidate_id="frozen-candidate",
                    candidate_config_sha256="b" * 64,
                    selection_evidence_sha256="c" * 64,
                    validation_end_at_utc=1000, selected_at_utc=1200,
                    registered_at_utc=1250, holdout_start_at_utc=2000,
                    holdout_end_at_utc=max(20000, 2100 + count * 100), embargo_seconds=100,
                    expected_holdout_count=count,
                    holdout_census_sha256=prepare_declared_holdout_census_sha256(census),
                    source=dict(provider="Synthetic", venue="Demo", instrument="XAUUSD-CFD",
                                quote_side="BID", account_alias="test-1",
                                settlement_currency="GBP", utc_convention="UTC",
                                archive_sha256="a" * 64))
    anchor = dict(manifest_sha256=prepare_declared_holdout_manifest_sha256(manifest),
                  anchored_at_utc=1300, anchor_reference="external-registry-id",
                  external_record_sha256="d" * 64)
    outcomes = [dict(row, observed_at_utc=row["label_available_at_utc"] + 25,
                     gross_cash="-5.00" if i == 5 else "10.00",
                     spread_cash="1.00", slippage_cash="1.00",
                     commission_cash="1.00", financing_cash="0.50", fx_cash="0.50",
                     receipt_sha256=f"{i + 100:064x}")
                for i, row in enumerate(census)]
    return manifest, census, anchor, outcomes, manifest["holdout_end_at_utc"] + 1


def audit(data=None):
    return audit_declared_holdout_release(*(fixture() if data is None else data))


def test_complete_declared_release_and_no_trade_permissions():
    result = audit()
    assert result["status"] == "DECLARED_EVALUATION_ONLY"
    assert result["observation_count"] == 35
    assert result["net_cash"] == "195.0000"  # 34 x 6, one x -9
    assert result["worst_observation_net_cash"] == "-9.0000"
    assert result["max_observation_end_drawdown_cash"] == "9.0000"
    assert result["anchor_independently_authenticated"] is False
    assert result["one_time_release_enforced"] is False
    assert result["holdout_untouched_independently_verified"] is False
    assert result["may_execute_demo_order"] is False
    assert result["may_execute_real_order"] is False
    assert result["profitable_edge_verified"] is False


def test_small_sample_withheld_even_if_net_positive():
    result = audit(fixture(2))
    assert result["status"] == "WITHHELD_INSUFFICIENT_HOLDOUT"
    assert result["outcome_metrics_withheld"] is True
    for key in ("net_cash", "worst_observation_net_cash",
                "max_observation_end_drawdown_cash", "outcome_receipts_sha256"):
        assert result[key] is None


def test_withheld_holdout_does_not_leak_outcome_changes():
    data = fixture(29)
    baseline = audit(data)
    modified = copy.deepcopy(data)
    for i, row in enumerate(modified[3]):
        row["gross_cash"] = "-999.00" if i % 2 else "999.00"
        row["financing_cash"] = "-500.00" if i % 2 else "500.00"
        row["receipt_sha256"] = f"{i + 5000:064x}"
    assert audit(modified) == baseline
    assert baseline["observation_count"] == 29
    assert baseline["outcome_metrics_withheld"] is True


def test_release_threshold_exposes_only_declared_not_verified_results():
    result = audit(fixture(30))
    assert result["status"] == "DECLARED_EVALUATION_ONLY"
    assert result["outcome_metrics_withheld"] is False
    assert result["net_cash"] is not None
    assert result["outcome_receipts_sha256"] is not None
    assert result["profitable_edge_verified"] is False


def test_outcome_order_independent_and_no_input_mutation():
    data = fixture()
    original = copy.deepcopy(data)
    result = audit(data)
    rng = random.Random(20261027)
    rng.shuffle(data[3])
    reordered = audit(data)
    assert result == reordered
    assert original[0] == data[0] and original[1] == data[1]
    assert original[2] == data[2]


def test_one_missing_or_duplicate_observation_rejected():
    data = list(fixture())
    data[3].pop()
    with pytest.raises(ValueError):
        audit(data)
    data = list(fixture())
    data[3][-1] = copy.deepcopy(data[3][0])
    with pytest.raises(ValueError):
        audit(data)


def test_frozen_census_change_rejected_even_if_count_same():
    data = list(fixture())
    data[1][3]["row_sha256"] = "f" * 64
    data[3][3]["row_sha256"] = "f" * 64
    with pytest.raises(ValueError, match="commitment"):
        audit(data)


def test_future_receipt_not_available_at_release():
    data = list(fixture())
    data[3][0]["observed_at_utc"] = data[4] + 1
    with pytest.raises(ValueError):
        audit(data)


def test_release_only_after_holdout_end():
    data = list(fixture())
    data[4] = 10000
    with pytest.raises(ValueError):
        audit(data)


def test_future_outcome_mutation_changes_only_outcome_receipts_and_net():
    data = fixture()
    before = audit(data)
    changed = copy.deepcopy(data)
    changed[3][-1]["gross_cash"] = "-100.00"
    after = audit(changed)
    assert before["manifest_sha256"] == after["manifest_sha256"]
    assert before["holdout_census_sha256"] == after["holdout_census_sha256"]
    assert before["net_cash"] != after["net_cash"]
    assert before["outcome_receipts_sha256"] != after["outcome_receipts_sha256"]


@pytest.mark.parametrize("mutate", [
    lambda d: d[0].update(holdout_profit="100000"),
    lambda d: d[0].update(registered_at_utc=2000),
    lambda d: d[0].update(registered_at_utc=1199),
    lambda d: d[0].update(selected_at_utc=1099),
    lambda d: d[0].update(selected_at_utc=True),
    lambda d: d[0].update(embargo_seconds=0),
    lambda d: d[0].update(embargo_seconds=2_592_001),
    lambda d: d[0].update(expected_holdout_count=1),
    lambda d: d[0].update(expected_holdout_count=True),
    lambda d: d[0].update(candidate_id=""),
    lambda d: d[0].update(candidate_config_sha256="bad"),
    lambda d: d[0].update(holdout_census_sha256="bad"),
    lambda d: d[0]["source"].update(extra="leak"),
    lambda d: d[0]["source"].update(archive_sha256="bad"),
    lambda d: d[0]["source"].update(quote_side="BID_ASK"),
    lambda d: d[0]["source"].update(utc_convention="LOCAL_DST"),
    lambda d: d[0]["source"].update(settlement_currency="gbp"),
    lambda d: d[0]["source"].update(account_alias=""),
    lambda d: d[1][0].update(gross_cash="100"),
    lambda d: d[1][0].update(source_sha256="b" * 64),
    lambda d: d[1][0].update(row_sha256="bad"),
    lambda d: d[1][0].update(decision_at_utc=2000 - 1),
    lambda d: d[1][0].update(label_available_at_utc=2100),
    lambda d: d[1][0].update(decision_at_utc=True),
    lambda d: d[1][0].update(observation_id="o0001"),
    lambda d: d[1][0].update(row_sha256=d[1][1]["row_sha256"]),
    lambda d: d[1].reverse(),
    lambda d: d[2].update(anchor_reference=""),
    lambda d: d[2].update(anchored_at_utc=2000),
    lambda d: d[2].update(anchored_at_utc=1249),
    lambda d: d[2].update(anchored_at_utc=True),
    lambda d: d[2].update(manifest_sha256="f" * 64),
    lambda d: d[2].update(external_record_sha256="bad"),
    lambda d: d[2].update(verified=True),
    lambda d: d[3][0].update(holdout_rank=1),
    lambda d: d[3][0].update(observation_id="o0001"),
    lambda d: d[3][0].update(row_sha256="f" * 64),
    lambda d: d[3][0].update(source_sha256="f" * 64),
    lambda d: d[3][0].update(decision_at_utc=2101),
    lambda d: d[3][0].update(label_available_at_utc=2151),
    lambda d: d[3][0].update(observed_at_utc=2149),
    lambda d: d[3][0].update(observed_at_utc=True),
    lambda d: d[3][0].update(gross_cash="NaN"),
    lambda d: d[3][0].update(gross_cash="1e9"),
    lambda d: d[3][0].update(gross_cash="-0"),
    lambda d: d[3][0].update(gross_cash=10.0),
    lambda d: d[3][0].update(gross_cash="10000000000"),
    lambda d: d[3][0].update(spread_cash="-1.00"),
    lambda d: d[3][0].update(slippage_cash="-0.00"),
    lambda d: d[3][0].update(commission_cash="-1"),
    lambda d: d[3][0].update(fx_cash="-1"),
    lambda d: d[3][0].update(financing_cash="-0.0"),
    lambda d: d[3][0].update(receipt_sha256="bad"),
    lambda d: d[3][0].update(receipt_sha256=d[3][1]["receipt_sha256"]),
    lambda d: d[4].__class__ is int and d.__setitem__(4, True),
])
def test_malformed_or_leaking_declarations_fail_closed(mutate):
    data = list(copy.deepcopy(fixture()))
    mutate(data)
    with pytest.raises(ValueError):
        audit(data)


def test_large_synthetic_holdout_population_and_randomized_costs():
    data = list(fixture(1000))
    rng = random.Random(20261027)
    for row in data[3]:
        row["gross_cash"] = str(rng.randint(-200, 200))
        row["spread_cash"] = str(rng.randint(0, 20))
        row["financing_cash"] = str(rng.randint(-20, 20))
    result = audit(data)
    assert result["observation_count"] == 1000
    assert result["may_execute_real_order"] is False
    # Independently recompute the signed exact-decimal sum.
    from decimal import Decimal
    expected = sum((Decimal(x["gross_cash"]) - Decimal(x["spread_cash"]) -
                    Decimal(x["slippage_cash"]) - Decimal(x["commission_cash"]) -
                    Decimal(x["financing_cash"]) - Decimal(x["fx_cash"]) for x in data[3]), Decimal(0))
    assert Decimal(result["net_cash"]) == expected


def test_empty_and_oversized_populations_rejected():
    with pytest.raises(ValueError):
        prepare_declared_holdout_census_sha256([])
    with pytest.raises(ValueError):
        prepare_declared_holdout_census_sha256([{}])
    with pytest.raises(ValueError):
        prepare_declared_holdout_census_sha256([fixture(1)[1][0]] * 10001)
