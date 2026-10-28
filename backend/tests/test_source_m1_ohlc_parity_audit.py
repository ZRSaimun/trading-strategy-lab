"""Synthetic read-only OHLC parity tests: no vendor data, network, files or DB."""
import pytest
from app.source_m1_ohlc_parity_audit import audit_source_m1_ohlc_parity

T = 1_790_000_100
assert T % 900 == 0


def row(i, o="1.0", h="2", l="0.5", c="1.50"):
    return (T + 60 * i, o, h, l, c)


def audit(source, stored, **kwargs):
    return audit_source_m1_ohlc_parity(source, stored, source_id=kwargs.pop("source_id", "synthetic:v1"), **kwargs)


def test_clean_numeric_decimal_parity_still_unverified():
    source = [row(0), row(1)]
    stored = [row(0, "1.00", "2.000", "0.50", "1.5"), row(1)]
    result = audit(source, stored)
    assert result["result"] == "EXACT_DECIMAL_PARITY_ONLY_UNVERIFIED"
    assert result["first_seen_source_ohlc_mismatched_in_store"] == 0
    assert result["research_ready"] is False
    assert result["may_execute_order"] is False
    assert result == audit(source, stored)


def test_duplicate_identical_rows_quarantined_even_when_store_matches():
    source = [row(0), row(1), row(0)]
    result = audit(source, [row(0), row(1)])
    assert result["source_repeated_rows"] == 1
    assert result["source_identical_repeated_rows"] == 1
    assert result["source_conflicting_repeated_rows"] == 0
    assert result["source_backward_timestamp_jumps"] == 1
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_conflicting_replay_quarantined_and_prices_not_exposed():
    source = [row(0), row(1), row(0, "1.1")]
    result = audit(source, [row(0), row(1)])
    assert result["source_conflicting_repeated_rows"] == 1
    assert result["first_seen_source_ohlc_mismatched_in_store"] == 0
    assert result["source_conflicting_repeated_samples"][0]["row_ordinal"] == 3
    assert "1.1" not in str(result)
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_stored_value_mismatch_detected_without_timestamp_difference():
    result = audit([row(0)], [row(0, "1.2")])
    assert result["source_unique_missing_from_store"] == 0
    assert result["stored_minutes_absent_from_source"] == 0
    assert result["first_seen_source_ohlc_mismatched_in_store"] == 1
    assert len(result["source_store_ohlc_mismatch_samples_utc"]) == 1
    assert result["result"] == "QUARANTINE_REQUIRED"


def test_missing_extra_minutes_and_disabled_samples():
    result = audit([row(0), row(1)], [row(0), row(2)], sample_limit=0)
    assert result["source_unique_missing_from_store"] == 1
    assert result["stored_minutes_absent_from_source"] == 1
    assert result["source_missing_from_store_samples_utc"] == []
    assert result["stored_absent_from_source_samples_utc"] == []


def test_negative_futures_prices_allowed_without_claiming_validity():
    negative = (T, "-2.5", "-1", "-3", "-2")
    result = audit([negative], [negative])
    assert result["result"] == "EXACT_DECIMAL_PARITY_ONLY_UNVERIFIED"


@pytest.mark.parametrize("bad", [
    (T, True, "2", "0.5", "1"), (T, 1.0, "2", "0.5", "1"),
    (T, "NaN", "2", "0.5", "1"), (T, "1e400", "2", "0.5", "1"),
    (T, "1", "0", "0.5", "1"), (T, "1", "2", "3", "1"),
    (T + 1, "1", "2", "0.5", "1"), (True, "1", "2", "0.5", "1"),
    (T, "1", "2", "0.5"), [T, "1", "2", "0.5", "1"],
    (T, "1.0000000000000", "2", "0.5", "1"),
])
def test_invalid_rows_fail_closed(bad):
    with pytest.raises(ValueError):
        audit([bad], [row(0)])


@pytest.mark.parametrize("bad", [[], "bad", [row(1), row(0)], [row(0), row(0)]])
def test_invalid_stored_population_fails_closed(bad):
    with pytest.raises(ValueError):
        audit([row(0)], bad)


@pytest.mark.parametrize("kwargs", [{"source_id": "../x"}, {"source_id": ""}, {"sample_limit": 21}, {"sample_limit": True}])
def test_invalid_options_fail_closed(kwargs):
    with pytest.raises(ValueError):
        audit([row(0)], [row(0)], **kwargs)


def test_no_mutation_and_fingerprint_detects_price_changes():
    source = [row(0), row(1)]
    snapshot = source[:]
    report = audit(source, source)
    changed = [row(0, "1.1"), row(1)]
    assert report["source_order_rows_sha256"] != audit(changed, changed)["source_order_rows_sha256"]
    assert source == snapshot
