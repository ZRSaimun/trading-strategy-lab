"""Synthetic-only fail-closed source/label leakage regressions."""
import copy
from datetime import datetime, timezone
import random

import pytest
from app.development_source_disjoint_audit import audit_development_source_disjointness


def at(year, month=1, day=1):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


def sample():
    archives = [dict(archive_id=f"a{year}", sha256=f"{year-2018:064x}",
                     first_at=at(year), end_at=at(year+1)) for year in range(2019, 2023)]
    manifest = dict(source=dict(provider="Synthetic", venue="OFFLINE", instrument="XAUUSD-CFD",
                                quote_side="BID", account_alias="research-1", settlement_currency="GBP",
                                utc_convention="UTC"), archives=archives, registered_at=at(2019, 12),
                    development_end=at(2023), validation_start=at(2023), holdout_start=at(2024),
                    embargo_seconds=86400, expected_observation_count=4)
    observations = [dict(observation_id=f"o{year}", archive_id=f"a{year}",
                         row_sha256=f"{year:064x}", row_at=at(year, 7),
                         feature_start_at=at(year, 6), decision_at=at(year, 7),
                         label_available_at=at(year, 7, 8)) for year in range(2019, 2023)]
    folds = [dict(fold_id=f"f{year}", train_start=at(2019), train_end=at(year)-86400,
                  test_start=at(year), test_end=at(year+1),
                  train_ids=[f"o{x}" for x in range(2019, year)], test_ids=[f"o{year}"])
             for year in range(2020, 2023)]
    return manifest, observations, folds


def run(m=None, o=None, f=None):
    a, b, c = sample()
    return audit_development_source_disjointness(a if m is None else m,
                                                 b if o is None else o,
                                                 c if f is None else f)


def test_three_year_expanding_folds_are_declared_only():
    result = run()
    assert result["status"] == "DECLARED_TIMING_ONLY"
    assert result["test_years"] == [2020, 2021, 2022]
    assert result["unique_test_observations"] == 3
    assert not any(result[k] for k in ("source_authenticated", "independent_preregistration_verified",
                                      "untouched_holdout_verified", "actual_costs_verified",
                                      "verified_profitability", "may_execute_order"))


def test_canonical_digest_independent_of_population_order():
    m, o, f = sample()
    original = copy.deepcopy((m, o, f))
    baseline = run(m, o, f)["declaration_sha256"]
    assert run(dict(m, archives=list(reversed(m["archives"]))), list(reversed(o)),
               [dict(x, train_ids=list(reversed(x["train_ids"]))) for x in f])["declaration_sha256"] == baseline
    assert (m, o, f) == original


def test_digest_binds_source_clocks_and_membership():
    m, o, f = sample()
    old = run(m, o, f)["declaration_sha256"]
    for change in (dict(m, registered_at=m["registered_at"]-1),
                   dict(m, source=dict(m["source"], account_alias="research-2"))):
        assert run(change, o, f)["declaration_sha256"] != old
    altered = copy.deepcopy(o)
    altered[0]["label_available_at"] += 1
    assert run(m, altered, f)["declaration_sha256"] != old


def test_two_years_withheld_not_promoted_to_multiyear():
    m, o, f = sample()
    m["expected_observation_count"] = 3
    result = run(m, o[:3], f[:2])
    assert result["status"] == "WITHHELD_INSUFFICIENT_MULTIYEAR"


@pytest.mark.parametrize("change", [
    lambda m,o,f: m.update(registered_at=at(2020)),
    lambda m,o,f: m.update(embargo_seconds=0),
    lambda m,o,f: m.update(expected_observation_count=5),
    lambda m,o,f: m.update(holdout_start=at(2023)),
    lambda m,o,f: m["source"].update(utc_convention="Europe/London"),
    lambda m,o,f: m["source"].update(quote_side="TRADE"),
    lambda m,o,f: m["source"].update(secret="not allowed"),
    lambda m,o,f: m["archives"][1].update(sha256=m["archives"][0]["sha256"]),
    lambda m,o,f: m["archives"][1].update(first_at=at(2019, 12)),
    lambda m,o,f: m["archives"][0].update(end_at=at(2020, 2)),
    lambda m,o,f: o[1].update(row_sha256=o[0]["row_sha256"]),
    lambda m,o,f: o[1].update(row_at=o[0]["row_at"]),
    lambda m,o,f: o[1].update(label_available_at=at(2023, 2)),
    lambda m,o,f: o[1].update(feature_start_at=at(2020, 8)),
    lambda m,o,f: o[1].update(returns="1.20"),
    lambda m,o,f: o[1].update(archive_id="missing"),
    lambda m,o,f: f[0].update(test_ids=["o2020", "o2020"]),
    lambda m,o,f: f[0].update(test_ids=["o2019"]),
    lambda m,o,f: f[1].update(train_ids=["o2019", "o2020", "o2021"]),
    lambda m,o,f: f[1].update(test_start=at(2020, 12)),
    lambda m,o,f: f[1].update(train_start=at(2020)),
    lambda m,o,f: f[1].update(train_end=at(2020)),
    lambda m,o,f: f[1].update(train_ids=["o2021"]),
    lambda m,o,f: f[2].update(test_ids=["o2021"]),
    lambda m,o,f: f[2].update(test_ids=["o2022", "o2020"]),
    lambda m,o,f: f[2].update(test_ids=["o2022"], train_ids=["o2019", "o2019"]),
])
def test_rejects_invalid_identity_clock_census_and_leakage(change):
    m, o, f = sample()
    change(m, o, f)
    with pytest.raises(ValueError):
        run(m, o, f)


def test_embargo_excludes_training_label_not_yet_known():
    m, o, f = sample()
    o[1]["label_available_at"] = at(2021) - 3600
    with pytest.raises(ValueError, match="embargo"):
        run(m, o, f)


def test_source_timestamp_reuse_even_with_different_row_hash_is_ambiguous():
    m, o, f = sample()
    o[2]["row_at"] = o[1]["row_at"]
    with pytest.raises(ValueError):
        run(m, o, f)


def test_seeded_population_order_property():
    m, o, f = sample()
    expected = run(m, o, f)["declaration_sha256"]
    rng = random.Random(20261027)
    for _ in range(250):
        aa, bb, cc = copy.deepcopy((m, o, f))
        rng.shuffle(aa["archives"])
        rng.shuffle(bb)
        for fold in cc:
            rng.shuffle(fold["train_ids"])
        assert run(aa, bb, cc)["declaration_sha256"] == expected


def test_undeclared_extra_observation_fails_census():
    m, o, f = sample()
    extra = dict(o[0], observation_id="unlisted", row_sha256="f"*64,
                 row_at=at(2019, 8), decision_at=at(2019, 8),
                 label_available_at=at(2019, 8, 8))
    o.append(extra)
    m["expected_observation_count"] += 1
    with pytest.raises(ValueError, match="census|Selective fold"):
        run(m, o, f)


def test_missing_observation_is_not_implicitly_excluded():
    m, o, f = sample()
    m["expected_observation_count"] = 3
    with pytest.raises(ValueError):
        run(m, o[1:], f)


@pytest.mark.parametrize("key,value", [
    ("registered_at", True), ("development_end", 1.2),
    ("embargo_seconds", True), ("expected_observation_count", False),
])
def test_boolean_and_float_clocks_rejected(key, value):
    m, o, f = sample()
    m[key] = value
    with pytest.raises(ValueError):
        run(m, o, f)


def test_test_window_must_not_reach_validation_or_holdout():
    m, o, f = sample()
    f[-1]["test_end"] = at(2023, 2)
    with pytest.raises(ValueError):
        run(m, o, f)


def test_outcome_fields_rejected_even_if_synthetic():
    m, o, f = sample()
    f[0]["net_profit"] = "100"
    with pytest.raises(ValueError, match="schema"):
        run(m, o, f)


def test_earlier_test_label_must_mature_before_reuse_as_training():
    m, o, f = sample()
    o[1]["label_available_at"] = at(2021, 1, 1)
    with pytest.raises(ValueError, match="embargo"):
        run(m, o, f)


def test_cannot_silently_drop_eligible_training_observation():
    m, o, f = sample()
    f[1]["train_ids"] = ["o2019"]
    with pytest.raises(ValueError, match="Selective fold"):
        run(m, o, f)


def test_cannot_silently_drop_eligible_test_observation():
    m, o, f = sample()
    extra = dict(o[1], observation_id="o2020b", row_sha256="e"*64,
                 row_at=at(2020, 8), decision_at=at(2020, 8),
                 label_available_at=at(2020, 8, 8))
    o.append(extra)
    m["expected_observation_count"] = 5
    f[1]["train_ids"].append("o2020b")
    f[2]["train_ids"].append("o2020b")
    # The extra observation is used in later training, but was omitted
    # from the first 2020 test fold: that omission must not pass.
    with pytest.raises(ValueError, match="Selective fold"):
        run(m, o, f)


def test_complete_expanding_census_with_extra_observation_is_allowed():
    m, o, f = sample()
    extra = dict(o[1], observation_id="o2020b", row_sha256="e"*64,
                 row_at=at(2020, 8), decision_at=at(2020, 8),
                 label_available_at=at(2020, 8, 8))
    o.append(extra)
    m["expected_observation_count"] = 5
    f[0]["test_ids"].append("o2020b")
    f[1]["train_ids"].append("o2020b")
    f[2]["train_ids"].append("o2020b")
    assert run(m, o, f)["unique_test_observations"] == 4
