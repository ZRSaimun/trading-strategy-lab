"""Synthetic as-of maturity vs missing-minute attribution; no market claims."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.offline_news_spike_attrition import audit_news_spike_attrition
from app.offline_news_spike_persistence import census_news_spike_persistence


EVENT = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)


def stamp(i):
    return (EVENT + timedelta(minutes=i)).isoformat()


def study(as_of, *, missing=()):
    candles = []
    for i in range(-15, as_of):
        if i in missing:
            continue
        high = "103" if i == 0 else "101"
        close = "102" if i == 0 else "100"
        candles.append({"time": stamp(i), "open": "100",
                        "high": high, "low": "99", "close": close})
    report = census_news_spike_persistence(
        candles, [{"event_id": "synthetic-fed", "time": stamp(0)}],
        as_of_utc=stamp(as_of), source_id="synthetic-bid",
    )
    return report, audit_news_spike_attrition(report)


@pytest.mark.parametrize("as_of,pending,missing", [
    (5, ("15", "30", "60"), ()),
    (15, ("30", "60"), ()),
    (20, (), ("15", "30", "60")),
    (65, (), ("15", "30", "60")),
])
def test_pending_vs_mature_missing_horizons(as_of, pending, missing):
    absent = (10,) if missing else ()
    source, audit = study(as_of, missing=absent)
    for h in ("5", "15", "30", "60"):
        row = audit["horizons"]["directional_total"][h]
        assert row["eligible"] == 1
        assert row["unknown"] == row["pending_unknown"] + row["missing_unknown"]
        assert row["pending_unknown"] == int(h in pending)
        assert row["missing_unknown"] == int(h in missing)
    assert source["events"][0]["spike"] == "up"


def test_matured_gap_taints_pending_later_cumulative_horizons():
    _, audit = study(20, missing=(10,))
    for horizon in ("15", "30", "60"):
        row = audit["horizons"]["up"][horizon]
        assert row["missing_unknown"] == 1
        assert row["pending_unknown"] == 0
    assert audit["horizons"]["up"]["5"]["unknown"] == 0


def test_as_of_boundary_maturity_not_pending():
    _, audit = study(15, missing=(10,))
    row = audit["horizons"]["up"]["15"]
    assert row["missing_unknown"] == 1
    assert row["pending_unknown"] == 0


def test_empty_population_has_zero_cause_counts_and_null_rates():
    source, _ = study(5)
    source["events"] = []
    result = audit_news_spike_attrition(source)
    row = result["horizons"]["directional_total"]["60"]
    assert (row["pending_unknown"], row["missing_unknown"], row["unknown"]) == (0, 0, 0)
    assert row["observed_alignment_fraction"] is None


def test_deterministic_no_input_mutation():
    source, result = study(20, missing=(10,))
    original = deepcopy(source)
    assert audit_news_spike_attrition(source) == result
    assert source == original
