"""Synthetic-only duplicate M15 quarantine sensitivity tests."""
import json
from dataclasses import replace
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.offline_sweep_probe import Bar
from app.offline_sweep_duplicate_bucket_sensitivity import (
    audit_declared_duplicate_minutes, main)

DATASET = "a" * 64
ARCHIVE = "b" * 64
START = datetime(2025, 1, 1)


def bars(n=100):
    return [Bar(START + timedelta(minutes=15 * i), Decimal("100.1"),
                Decimal("101"), Decimal("99"), Decimal("100.2"), 0)
            for i in range(n)]


def run(candles, duplicates):
    return audit_declared_duplicate_minutes(
        candles, duplicates, dataset_id=DATASET, archive_sha256=ARCHIVE)


def test_no_duplicate_manifest_preserves_original_census():
    report = run(bars(), [])
    assert report["original"] == report["quarantined_sensitivity"]
    assert report["quarantined_complete_m15_buckets"] == 0
    assert report["cohort_split_index_preserved"] is True
    assert report["verified_profitability"] is False
    assert report["may_execute_order"] is False


def test_repeated_hour_quarantines_four_distinct_complete_buckets():
    candles = bars(120)
    source_before = list(candles)
    duplicates = [(START + timedelta(minutes=i)).isoformat(timespec="seconds")
                  for i in range(60, 120)]
    report = run(candles, duplicates)
    assert report["declared_duplicate_m1_count"] == 60
    assert report["declared_distinct_touched_m15_buckets"] == 4
    assert report["quarantined_complete_m15_buckets"] == 4
    assert report["retained_m15_count"] == 120
    assert candles == source_before
    assert report["matched_trade_population_preserved"] is False
    assert report["duplicate_source_rows_authenticated"] is False


def test_missing_partial_bucket_is_not_counted_as_complete():
    report = run(bars(100), ["2025-01-10T00:01:00"])
    assert report["declared_buckets_not_in_complete_m15_population"] == 1
    assert report["quarantined_complete_m15_buckets"] == 0


@pytest.mark.parametrize("bad", [
    ["2025-01-01T00:01:00", "2025-01-01T00:01:00"],
    ["2025-01-01T00:02:00", "2025-01-01T00:01:00"],
    ["2025-01-01T00:01:01"],
    ["2025-01-01T00:01:00Z"],
    ["not-a-time"],
])
def test_bad_duplicate_minute_declarations_fail_closed(bad):
    with pytest.raises(ValueError):
        run(bars(), bad)


def test_nonchronological_and_invalid_price_rejected():
    original = bars()
    with pytest.raises(ValueError, match="chronological"):
        run(original[:2] + [original[1]] + original[3:], [])
    broken = list(original)
    broken[2] = replace(broken[2], h=Decimal("1"))
    with pytest.raises(ValueError, match="geometry"):
        run(broken, [])


def test_cli_closed_schema_and_machine_readable(tmp_path, capsys):
    payload = {"dataset_id": DATASET, "archive_sha256": ARCHIVE,
               "duplicate_m1_times": ["2025-01-01T00:01:00"],
               "bars": [{"time": b.time.isoformat(timespec="seconds"),
                         "o": str(b.o), "h": str(b.h), "l": str(b.l),
                         "c": str(b.c), "segment": b.segment} for b in bars()]}
    path = tmp_path / "declared.json"
    path.write_text(json.dumps(payload))
    main([str(path)])
    result = json.loads(capsys.readouterr().out)
    assert result["quarantined_complete_m15_buckets"] == 1
    assert result["executable_bid_ask_costs_verified"] is False
    path.write_text('{"dataset_id":"x","dataset_id":"y"}')
    with pytest.raises(ValueError, match="Duplicate JSON"):
        main([str(path)])


def test_isolation_preserves_bar_positions_and_breaks_all_crossing_windows(monkeypatch):
    import app.offline_sweep_duplicate_bucket_sensitivity as sensitivity
    captured = []
    original_research = sensitivity.research

    def inspect(bars):
        captured.append(list(bars))
        return original_research(bars)

    monkeypatch.setattr(sensitivity, "research", inspect)
    original = bars(120)
    duplicate = [(START + timedelta(minutes=i)).isoformat(timespec="seconds")
                 for i in range(60, 120)]
    run(original, duplicate)
    assert len(captured) == 2
    before, after = captured
    assert len(before) == len(after) == 120
    assert [x.time for x in before] == [x.time for x in after]
    assert [(x.o, x.h, x.l, x.c) for x in before] == [
        (x.o, x.h, x.l, x.c) for x in after]
    assert [x.segment for x in after[:10]] == [0, 0, 0, 0, 1, 2, 3, 4, 5, 5]


def test_nonfinite_decimal_and_boolean_segment_rejected():
    original = bars()
    bad = list(original)
    bad[3] = replace(bad[3], c=Decimal("NaN"))
    with pytest.raises(ValueError):
        run(bad, [])
    bad = list(original)
    bad[3] = replace(bad[3], segment=True)
    with pytest.raises(ValueError, match="identity"):
        run(bad, [])
