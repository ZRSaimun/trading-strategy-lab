"""Synthetic-only deterministic reversal / news-spike censoring regressions."""
from datetime import datetime, timedelta, timezone
import copy
import pytest
from app.offline_news_spike_reversal import census_news_spike_reversal

T = datetime(2026, 10, 28, 18, tzinfo=timezone.utc)


def ts(i):
    return (T + timedelta(minutes=i)).isoformat()


def bars(*, direction="up", return_at=None, opposite_at=None, missing=(), end=60):
    result = []
    for i in range(-15, end):
        if i in missing:
            continue
        high, low, close = "101", "99", "100"
        if i >= 0:
            if direction == "up":
                high, low, close = "104", "101", "103"
            elif direction == "down":
                high, low, close = "99", "96", "97"
            elif direction == "both":
                high, low, close = "104", "96", "100"
            if return_at is not None and i >= return_at:
                close = "100"
                high = "104" if direction == "up" else "101"
                low = "99" if direction == "up" else "96"
            if opposite_at is not None and i >= opposite_at:
                if direction == "up":
                    low = "96"
                else:
                    high = "104"
        # use open=close to keep OHLC internally valid; independent bar opens allowed
        result.append({"time": ts(i), "open": close, "high": high, "low": low, "close": close})
    return result


def run(rows=None, *, as_of=61, events=None):
    return census_news_spike_reversal(rows if rows is not None else bars(),
        events if events is not None else [{"event_id": "E", "time": ts(0)}],
        as_of_utc=ts(as_of), source_id="synthetic-BID")


def test_up_first_bar_rejection():
    event = run(bars(return_at=0))["events"][0]
    assert event["initial_spike"] == "up"
    assert event["horizons"]["5"]["first_return_minute"] == 1
    assert event["horizons"]["60"]["first_opposite_sweep_minute"] is None


def test_down_reversal_and_opposite_sweep():
    event = run(bars(direction="down", return_at=7, opposite_at=9))["events"][0]
    assert event["initial_spike"] == "down"
    assert event["horizons"]["5"]["first_return_minute"] is None
    assert event["horizons"]["15"]["first_return_minute"] == 8
    assert event["horizons"]["15"]["first_opposite_sweep_minute"] == 10


def test_up_opposite_sweep_without_return_to_range():
    event = run(bars(opposite_at=8))["events"][0]
    assert event["horizons"]["15"]["first_opposite_sweep_minute"] == 9
    assert event["horizons"]["15"]["first_return_minute"] is None


def test_no_reversal_counts():
    report = run()
    assert report["horizons"]["60"]["return_to_range"]["no"] == 1
    assert report["horizons"]["60"]["return_to_range"]["observed_fraction"] == "0.000000"


def test_strict_break_equality_not_directional():
    rows = bars(direction="none")
    event = run(rows)["events"][0]
    assert event["status"] == "non_directional_initial_spike"
    assert run(rows)["directional_eligible"] == 0


def test_both_side_break_excluded():
    event = run(bars(direction="both"))["events"][0]
    assert event["initial_spike"] == "both" and event["horizons"] is None


def test_missing_pre_event():
    assert run(bars(missing=(-1,)))["events"][0]["status"] == "missing_pre_event_minutes"


def test_pending_first_five_not_mislabeled_missing():
    assert run(bars(end=2), as_of=2)["events"][0]["status"] == "pending_first_five_completion"


def test_missing_first_five_after_maturity():
    assert run(bars(missing=(2,)))["events"][0]["status"] == "missing_first_five_minutes"


def test_pending_horizons_and_unknown_bounds():
    report = run(bars(end=10), as_of=10)
    h = report["events"][0]["horizons"]
    assert h["5"]["status"] == "observed"
    assert h["15"]["status"] == "pending_horizon"
    assert report["horizons"]["15"]["return_to_range"]["all_eligible_upper_bound"] == "1.000000"


def test_gap_censors_horizon_and_preserves_earlier():
    report = run(bars(return_at=3, missing=(17,)))
    assert report["events"][0]["horizons"]["15"]["first_return_minute"] == 4
    assert report["events"][0]["horizons"]["30"]["status"] == "missing_horizon_minutes"
    assert report["horizons"]["30"]["return_to_range"]["missing"] == 1


def test_missing_before_reversal_censors_all_later():
    report = run(bars(return_at=20, missing=(12,)))
    assert report["events"][0]["horizons"]["60"]["first_return_minute"] is None


def test_no_future_or_uncompleted_candles():
    with pytest.raises(ValueError, match="Uncompleted"):
        run(bars(end=60), as_of=10)


def test_duplicate_and_unsorted_rejected():
    rows = bars()
    with pytest.raises(ValueError, match="duplicate"):
        run(rows + [rows[-1]])


def test_non_utc_and_nonminute_rejected():
    rows = bars()
    rows[0]["time"] = "2026-10-28T18:45:00+01:00"
    with pytest.raises(ValueError, match="UTC"):
        run(rows)
    with pytest.raises(ValueError, match="minute"):
        run([], as_of=0, events=[{"event_id":"E", "time":"2026-10-28T18:00:01Z"}])


def test_nonfinite_invalid_ohlc_and_extra_keys_rejected():
    for change, match in [({"high": "NaN"}, "Finite"), ({"low": "110"}, "Inconsistent"),
                          ({"other": "x"}, "Closed-schema")]:
        rows = bars()
        rows[0].update(change)
        with pytest.raises(ValueError, match=match):
            run(rows)


def test_overlapping_events_rejected():
    with pytest.raises(ValueError, match="overlapping"):
        run(events=[{"event_id":"a", "time":ts(0)}, {"event_id":"b", "time":ts(20)}])


def test_duplicate_event_id_rejected():
    with pytest.raises(ValueError, match="Unique"):
        run(events=[{"event_id":"a", "time":ts(0)}, {"event_id":"a", "time":ts(75)}])


def test_no_mutation_and_deterministic():
    rows = bars(return_at=6)
    before = copy.deepcopy(rows)
    assert run(rows) == run(rows)
    assert rows == before


def test_empty_population_has_no_invented_fraction():
    report = run([], events=[])
    assert report["directional_eligible"] == 0
    assert report["horizons"]["60"]["return_to_range"]["observed_fraction"] is None


def test_bounds_include_unknown_without_imputation():
    report = run(bars(end=10), as_of=10)
    row = report["horizons"]["60"]["opposite_sweep"]
    assert (row["yes"], row["no"], row["pending"], row["missing"]) == (0,0,1,0)
    assert row["all_eligible_lower_bound"] == "0.000000"
    assert row["all_eligible_upper_bound"] == "1.000000"


def test_known_completed_gap_taints_immature_later_horizons():
    report = run(bars(missing=(10,), end=20), as_of=20)
    hs = report["events"][0]["horizons"]
    assert hs["5"]["status"] == "observed"
    assert hs["15"]["status"] == "missing_horizon_minutes"
    assert hs["30"]["status"] == "missing_horizon_minutes"
    assert hs["60"]["status"] == "missing_horizon_minutes"
    for horizon in ("30", "60"):
        row = report["horizons"][horizon]["return_to_range"]
        assert (row["yes"], row["no"], row["pending"], row["missing"]) == (0, 0, 0, 1)
        assert row["all_eligible_upper_bound"] == "1.000000"


def test_no_known_gap_keeps_unfinished_horizons_pending():
    report = run(bars(end=20), as_of=20)
    hs = report["events"][0]["horizons"]
    assert hs["15"]["status"] == "observed"
    assert hs["30"]["status"] == "pending_horizon"
    assert hs["60"]["status"] == "pending_horizon"


def test_missing_minute_is_not_missing_before_its_close():
    before = run(bars(end=20), as_of=20)
    assert before["events"][0]["horizons"]["30"]["status"] == "pending_horizon"
    after = run(bars(missing=(20,), end=21), as_of=21)
    assert after["events"][0]["horizons"]["30"]["status"] == "missing_horizon_minutes"
    assert after["events"][0]["horizons"]["60"]["status"] == "missing_horizon_minutes"


def test_downward_spike_known_gap_has_same_censoring():
    report = run(bars(direction="down", missing=(9,), end=16), as_of=16)
    assert report["events"][0]["initial_spike"] == "down"
    for horizon in ("15", "30", "60"):
        assert report["events"][0]["horizons"][horizon]["status"] == "missing_horizon_minutes"


def test_gap_censoring_is_deterministic_and_read_only():
    source = bars(missing=(8,), end=20)
    original = copy.deepcopy(source)
    a = run(source, as_of=20)
    b = run(source, as_of=20)
    assert a == b
    assert source == original
