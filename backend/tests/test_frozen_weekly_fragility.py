"""Synthetic-only weekly concentration tests, not observed trading evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_population import fingerprint_population_manifest
from app.frozen_weekly_fragility import audit_frozen_weekly_fragility

BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
SOURCE = dict(instrument='NSXUSD-CFD', provider='synthetic', venue='synthetic',
              archive_sha256='a' * 64, price_side='BID', horizon_minutes=1)


def sample(n=36):
    eligible, paths = [], []
    for i in range(n):
        t = int((BASE + timedelta(weeks=i)).timestamp())
        frozen = dict(path_id=f'p{i}', signal_at=t, direction='LONG',
                      entry='100', stop='99', target='102')
        eligible.append(frozen)
        paths.append(dict(**SOURCE, **frozen, entry_at=t + 60,
                          bars=[dict(at=t + 60, open='100', high='100.5',
                                     low='99.5', close='99.5')]))
    return (dict(protocol='m1-bracket-population-v1', source=deepcopy(SOURCE),
                 eligible_signals=eligible, excluded_signals=[]), paths)


def run(m, p):
    return audit_frozen_weekly_fragility(m, p, fingerprint_population_manifest(m))


def test_complete_weekly_cost_sensitivity_and_leave_one_out():
    m, p = sample()
    result = run(m, p)
    assert result['status'] == 'DESCRIPTIVE_WEEKLY_FRAGILITY_ONLY'
    assert result['active_utc_weeks'] == 36
    assert result['maximum_signals_in_active_week'] == 1
    assert [x['additional_round_trip_bps'] for x in result['cost_scenarios']] == [0, 5, 10, 20]
    zero, five = result['cost_scenarios'][:2]
    assert zero['total_lower_net_r'] == '-18.0'
    assert zero['least_favorable_leave_one_week_out_lower_total_r'] == '-17.5'
    assert zero['certainly_negative_utc_weeks'] == 36
    assert zero['certainly_positive_utc_weeks'] == 0
    assert five['total_lower_net_r'] == '-19.80'
    assert five['least_favorable_leave_one_week_out_lower_total_r'] == '-19.25'
    assert result['verified_profitability'] is False
    assert result['executable_broker_fills'] is False


def test_one_positive_week_drives_fragility():
    m, p = sample()
    p[0]['bars'][0]['close'] = '101.5'
    p[0]['bars'][0]['high'] = '101.5'
    report = run(m, p)['cost_scenarios'][0]
    assert report['total_lower_net_r'] == '-16.0'
    assert report['least_favorable_leave_one_week_out_lower_total_r'] == '-17.5'
    assert report['certainly_positive_utc_weeks'] == 1
    assert report['certainly_negative_utc_weeks'] == 35


def test_ambiguous_touch_preserves_lower_upper_uncertainty():
    m, p = sample()
    p[0]['bars'][0] = dict(at=p[0]['entry_at'], open='100', high='103', low='98', close='100')
    report = run(m, p)['cost_scenarios'][0]
    assert report['total_lower_net_r'] == '-18.5'
    assert report['total_upper_net_r'] == '-15.5'
    assert report['sign_ambiguous_utc_weeks'] == 1


def test_shuffled_inputs_are_canonical():
    m, p = sample()
    expected = run(m, p)
    m['eligible_signals'].reverse()
    p.reverse()
    assert run(m, p) == expected


def test_two_signals_in_same_week_counted_once():
    m, p = sample()
    # Move a second completed signal to the same week as the first.
    t = m['eligible_signals'][0]['signal_at'] + 86400
    m['eligible_signals'][1]['signal_at'] = t
    p[1]['signal_at'] = t
    p[1]['entry_at'] = t + 60
    p[1]['bars'][0]['at'] = t + 60
    result = run(m, p)
    assert result['active_utc_weeks'] == 35
    assert result['maximum_signals_in_active_week'] == 2
    assert result['most_populated_weeks'][0]['signals'] == 2


def test_censored_outcome_withholds_all_weekly_returns():
    m, p = sample()
    p[0]['bars'] = []
    result = run(m, p)
    assert result['status'] == 'WITHHELD_INCOMPLETE_OR_INSUFFICIENT'
    assert result['cost_scenarios'] == []


def test_declared_exclusion_withholds():
    m, p = sample()
    m['excluded_signals'].append(dict(path_id='excluded',
                                      signal_at=int((BASE + timedelta(weeks=50)).timestamp()),
                                      reason='PRE_SIGNAL_DATA_GAP'))
    assert run(m, p)['cost_scenarios'] == []


def test_insufficient_sample_withholds():
    m, p = sample(11)
    assert run(m, p)['cost_scenarios'] == []


def test_changed_external_frozen_digest_rejected():
    m, p = sample()
    with pytest.raises(ValueError, match='SHA-256'):
        audit_frozen_weekly_fragility(m, p, 'f' * 64)


def test_duplicate_path_or_changed_source_rejected():
    m, p = sample()
    p[1]['path_id'] = p[0]['path_id']
    with pytest.raises(ValueError):
        run(m, p)
    m, p = sample()
    p[1]['venue'] = 'different'
    with pytest.raises(ValueError):
        run(m, p)


def test_gap_and_incomplete_path_are_not_survivor_filtered():
    m, p = sample()
    p[0]['bars'][0]['at'] += 60
    assert run(m, p)['cost_scenarios'] == []


def test_exact_decimal_not_float_in_long_sample():
    m, p = sample(80)
    report = run(m, p)
    assert report['cost_scenarios'][0]['total_lower_net_r'] == '-40.0'
    assert report['active_utc_weeks'] == 80
