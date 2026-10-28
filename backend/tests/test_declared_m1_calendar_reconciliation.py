"""Synthetic declared-calendar reconciliation; no provider, database or network."""
import pytest

from app.declared_m1_calendar_reconciliation import audit_declared_m1_coverage

T = 1_790_000_040  # aligned UTC minute


def audit(observed, expected, **kwargs):
    return audit_declared_m1_coverage(
        observed, expected, declaration_id="offline-calendar:v1", **kwargs
    )


def test_exact_match_is_still_unverified():
    result = audit([T, T + 60], [T, T + 60])
    assert result["matched_declared_minutes"] == 2
    assert result["unobserved_declared_minutes"] == 0
    assert result["observed_undeclared_minutes"] == 0
    assert result["independent_calendar_verified"] is False
    assert result["missing_market_data_proven"] is False
    assert result["live"] is False
    assert result["may_execute_order"] is False


def test_declared_session_gap_is_not_assumed_to_be_a_market_outage():
    expected = [T, T + 60, T + 120, T + 180]
    observed = [T - 60, T, T + 180, T + 240]
    result = audit(observed, expected)
    assert result["matched_declared_minutes"] == 2
    assert result["unobserved_declared_minutes"] == 2
    assert result["observed_undeclared_minutes"] == 2
    assert len(result["unobserved_declared_samples_utc"]) == 2
    assert len(result["observed_undeclared_samples_utc"]) == 2
    assert result["missing_market_data_proven"] is False


def test_weekend_not_in_declared_inventory_is_not_counted_missing():
    # A gap in wall time is not missing from an explicit expected list.
    result = audit([T, T + 3 * 86400], [T, T + 3 * 86400])
    assert result["unobserved_declared_minutes"] == 0


def test_zero_observations_is_reportable_not_a_fake_candle():
    result = audit([], [T, T + 60])
    assert result["observed_minutes"] == 0
    assert result["unobserved_declared_minutes"] == 2
    assert result["observed_undeclared_minutes"] == 0


def test_bounded_samples_and_fingerprints_are_deterministic():
    expected = [T + i * 60 for i in range(30)]
    first = audit([], expected, sample_limit=3)
    second = audit([], expected, sample_limit=3)
    assert first == second
    assert first["unobserved_declared_minutes"] == 30
    assert len(first["unobserved_declared_samples_utc"]) == 3
    assert len(first["declared_inventory_sha256"]) == 64
    assert first["declared_inventory_sha256"] != first["observed_inventory_sha256"]


@pytest.mark.parametrize("observed,expected", [
    ([T, T], [T]),                   # duplicate observed
    ([T + 60, T], [T]),              # unsorted observed
    ([T + 1], [T]),                  # unaligned observed
    ([True], [T]),                   # bool is not an epoch
    ([T], [T, T]),                   # duplicate expected
    ([T], [T + 1]),                  # unaligned expected
    ([T], []),                       # no declared calendar
    ([T], [253402300800]),          # outside representable UTC datetime
    ([T], "not-a-list"),             # invalid shape
])
def test_invalid_inventories_fail_closed(observed, expected):
    with pytest.raises(ValueError):
        audit(observed, expected)


@pytest.mark.parametrize("identifier", ["", "bad identifier", "../unsafe", "x" * 129, 42, None])
def test_declaration_id_is_bounded_and_safe(identifier):
    with pytest.raises(ValueError):
        audit([T], [T], declaration_id=identifier)


@pytest.mark.parametrize("sample_limit", [-1, 21, True, 1.5, "5"])
def test_sample_limit_must_be_bounded_integer(sample_limit):
    with pytest.raises(ValueError):
        audit([T], [T], sample_limit=sample_limit)


def test_input_lists_are_not_modified():
    observed = [T, T + 120]
    expected = [T, T + 60]
    audit(observed, expected)
    assert observed == [T, T + 120]
    assert expected == [T, T + 60]


def test_inventory_size_is_bounded_before_iteration():
    with pytest.raises(ValueError):
        audit([], [T + 60 * i for i in range(100_001)])
