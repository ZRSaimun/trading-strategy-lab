"""Synthetic aggregation checks: never claims actual vendor authentication."""
import hashlib
import json
import pytest
from app.offline_m1_multi_archive_census import audit_m1_multi_archive_census, BODY_KEYS, POLICY


def receipt(archive='a', manifest='c', count=2, mean=1.0, instrument='NSXUSD'):
    # Model the original engine's integer outcome wins; a fractional winner
    # count is impossible even when a fabricated report is self-rehashed.
    dev_count = count * 7 // 10
    later_count = count - dev_count
    dev_wins = dev_count // 2
    later_wins = later_count // 2

    def part(n, wins):
        return {'count': n, 'mean_gross_bps': mean if n else None,
                'mean_net_bps_by_roundtrip_cost': {str(c): round(mean-c, 6) if n else None for c in (0, 5, 10, 20)},
                'gross_win_fraction': round(wins / n, 6) if n else None}

    r = {'policy': POLICY, 'source': {'instrument': instrument, 'provider': 'HistData',
          'archive_sha256': archive*64, 'price_side': 'UNVERIFIED_SINGLE_SIDE',
          'time_convention': 'SOURCE_WALL_UNVERIFIED'},
         'bar_count': 100, 'bar_manifest_sha256': manifest*64,
         'timestamp_discontinuities': 0, 'backward_jumps': 0, 'adjacent_duplicates': 0,
         'sweep_count': count, 'ambiguous_count': 0, 'confirmed_count': count,
         'censored_gap_or_end': 0, 'excluded_overlap': 0, 'horizon_minutes': 15,
         'roundtrip_cost_bps': [0, 5, 10, 20],
         'development_exploratory': part(dev_count, dev_wins),
         'later_exploratory_not_holdout': part(later_count, later_wins),
         'all_exploratory': part(count, dev_wins + later_wins),
         'research_schema_version': 1, 'research_only': True,
         'trade_authorized': False, 'verified_profitability': False,
         'protected_holdout': False, 'source_authenticity_verified': False,
         'executable_quotes_verified': False, 'financing_modeled': False,
         'market_calendar_verified': False}
    return rehash(r)

def rehash(r):
    r['research_sha256'] = hashlib.sha256(json.dumps({k: r[k] for k in BODY_KEYS},
        sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()
    return r


def pair():
    return [receipt('a', 'c', count=2, mean=1.0), receipt('b', 'd', count=3, mean=3.0)]


def test_weighted_costs_and_non_execution():
    x = audit_m1_multi_archive_census(pair())
    g = x['groups'][0]
    assert g['archive_count'] == 2 and g['evaluated_count'] == 5
    assert g['weighted_mean_gross_bps_rounded_receipts'] == 2.2
    assert g['weighted_mean_net_bps_by_illustrative_cost']['5'] == -2.8
    assert g['all_nonempty_archives_negative_at_5bps'] is True
    assert x['research_only'] and not x['trade_authorized'] and not x['verified_profitability']


def test_reorder_has_identical_fingerprint():
    a = pair()
    assert audit_m1_multi_archive_census(a) == audit_m1_multi_archive_census(a[::-1])


def test_source_isolation():
    a, b = pair()
    b['source']['instrument'] = 'XAUUSD'
    rehash(b)
    x = audit_m1_multi_archive_census([b, a])
    assert len(x['groups']) == 2
    assert [y['instrument'] for y in x['groups']] == ['NSXUSD', 'XAUUSD']


def test_duplicate_archive_rejected():
    a, b = pair()
    b['source']['archive_sha256'] = a['source']['archive_sha256']
    rehash(b)
    with pytest.raises(ValueError, match='Duplicate'):
        audit_m1_multi_archive_census([a, b])


def test_duplicate_manifest_rejected():
    a, b = pair()
    b['bar_manifest_sha256'] = a['bar_manifest_sha256']
    rehash(b)
    with pytest.raises(ValueError, match='Duplicate'):
        audit_m1_multi_archive_census([a, b])


def test_tampered_mean_hash_rejected():
    a, b = pair()
    b['all_exploratory']['mean_gross_bps'] = 50
    with pytest.raises(ValueError, match='fingerprint'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_false_net_cost_rejected():
    a, b = pair()
    b['all_exploratory']['mean_net_bps_by_roundtrip_cost']['5'] = 100
    rehash(b)
    with pytest.raises(ValueError, match='cost scenario'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_population_mismatch_rejected():
    a, b = pair()
    b['confirmed_count'] = 999
    rehash(b)
    with pytest.raises(ValueError, match='population'):
        audit_m1_multi_archive_census([a, b])


def test_empty_receipt_does_not_grant_all_negative():
    a = receipt('a', 'c', count=0)
    b = receipt('b', 'd', count=2, mean=-1)
    x = audit_m1_multi_archive_census([a, b])
    assert x['groups'][0]['all_nonempty_archives_negative_at_5bps'] is None


def test_all_empty_returns_unknown_means():
    a = receipt('a', 'c', count=0)
    b = receipt('b', 'd', count=0)
    x = audit_m1_multi_archive_census([a, b])
    assert x['groups'][0]['weighted_mean_gross_bps_rounded_receipts'] is None


def test_unverified_status_must_remain_false():
    a, b = pair()
    a['source_authenticity_verified'] = True
    with pytest.raises(ValueError, match='unverified'):
        audit_m1_multi_archive_census([a, b])


@pytest.mark.parametrize('value', [[], [receipt()], 'bad', [None, receipt()]])
def test_invalid_report_cohorts(value):
    with pytest.raises(ValueError):
        audit_m1_multi_archive_census(value)


def test_negative_after_5_not_claimed_when_positive():
    a = receipt('a', 'c', count=2, mean=6)
    b = receipt('b', 'd', count=3, mean=1)
    x = audit_m1_multi_archive_census([a, b])
    assert x['groups'][0]['all_nonempty_archives_negative_at_5bps'] is False


def test_rehashed_partition_population_mismatch_rejected():
    a, b = pair()
    b['development_exploratory']['count'] = 0
    b['development_exploratory']['mean_gross_bps'] = None
    b['development_exploratory']['gross_win_fraction'] = None
    b['development_exploratory']['mean_net_bps_by_roundtrip_cost'] = {str(c): None for c in (0, 5, 10, 20)}
    rehash(b)
    with pytest.raises(ValueError, match='partition population'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_partition_mean_mismatch_rejected():
    a, b = pair()
    b['development_exploratory']['mean_gross_bps'] = 50
    b['development_exploratory']['mean_net_bps_by_roundtrip_cost'] = {str(c): 50-c for c in (0, 5, 10, 20)}
    rehash(b)
    with pytest.raises(ValueError, match='partition gross'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_partition_cost_mismatch_rejected():
    a, b = pair()
    b['later_exploratory_not_holdout']['mean_net_bps_by_roundtrip_cost']['10'] = 99
    rehash(b)
    with pytest.raises(ValueError, match='cost scenario'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_invalid_win_fraction_rejected():
    a, b = pair()
    b['all_exploratory']['gross_win_fraction'] = 1.1
    rehash(b)
    with pytest.raises(ValueError, match='win fraction'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_empty_partition_fabricated_return_rejected():
    a = receipt('a', 'c', count=1)
    b = receipt('b', 'd', count=3)
    a['development_exploratory']['mean_net_bps_by_roundtrip_cost']['5'] = 0
    rehash(a)
    with pytest.raises(ValueError, match='Empty exploratory'):
        audit_m1_multi_archive_census([a, b])


def test_one_outcome_partition_and_six_decimal_rounding():
    a = receipt('a', 'c', count=1, mean=0.000001)
    b = receipt('b', 'd', count=3, mean=0.000002)
    x = audit_m1_multi_archive_census([a, b])
    assert x['groups'][0]['evaluated_count'] == 4
    assert x['groups'][0]['weighted_mean_gross_bps_rounded_receipts'] == 0.000002


def test_rehashed_evaluated_count_above_bar_count_rejected():
    a, b = pair()
    b['bar_count'] = 2
    rehash(b)
    # The stronger scan bound now rejects the impossible confirmation
    # population before the older evaluated-count upper-bound check.
    with pytest.raises(ValueError, match='scan bounds'):
        audit_m1_multi_archive_census([a, b])


# Counter and win-fraction consistency: re-hashing cannot hide contradictions.
@pytest.mark.parametrize('field,bad', [
    ('timestamp_discontinuities', -1),
    ('backward_jumps', True),
    ('adjacent_duplicates', 1.5),
    ('sweep_count', '2'),
    ('ambiguous_count', -2),
])
def test_rehashed_invalid_diagnostic_counter_rejected(field, bad):
    a, b = pair()
    b[field] = bad
    rehash(b)
    with pytest.raises(ValueError, match='diagnostic'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_discontinuity_subcounts_exceed_total_rejected():
    a, b = pair()
    b['timestamp_discontinuities'] = 1
    b['backward_jumps'] = 1
    b['adjacent_duplicates'] = 1
    rehash(b)
    with pytest.raises(ValueError, match='discontinuity'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_discontinuities_exceed_possible_transitions_rejected():
    a, b = pair()
    b['timestamp_discontinuities'] = 100
    rehash(b)
    with pytest.raises(ValueError, match='discontinuity'):
        audit_m1_multi_archive_census([a, b])


@pytest.mark.parametrize('field,value', [
    ('sweep_count', 101),
    ('confirmed_count', 4),
    ('ambiguous_count', 201),
])
def test_rehashed_impossible_sweep_population_rejected(field, value):
    a, b = pair()
    b[field] = value
    # Keep original confirmed/evaluated population intact when testing
    # independent scan upper bounds.
    rehash(b)
    with pytest.raises(ValueError, match='scan bounds'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_partition_win_fraction_mismatch_rejected():
    a, b = pair()
    b = receipt('b', 'd', count=10, mean=1)
    b['development_exploratory']['gross_win_fraction'] = round(4 / 7, 6)
    rehash(b)
    with pytest.raises(ValueError, match='integer win counts'):
        audit_m1_multi_archive_census([a, b])


def test_partition_win_fraction_independent_rounding_tolerated():
    a, b = pair()
    # 3 / 7 and 1 / 3 require independent six-decimal rounding.
    b = receipt('b', 'd', count=7, mean=1)
    assert b['all_exploratory']['gross_win_fraction'] == round(3 / 7, 6)
    assert audit_m1_multi_archive_census([a, b])['report_count'] == 2


def test_source_wall_counter_bounds_accept_consistent_gaps():
    a, b = pair()
    b['timestamp_discontinuities'] = 3
    b['backward_jumps'] = 1
    b['adjacent_duplicates'] = 1
    rehash(b)
    assert audit_m1_multi_archive_census([a, b])['report_count'] == 2

# Original-v1 integer-win feasibility: a self-hash cannot invent half a win.
@pytest.mark.parametrize('count,impossible', [(1, 0.5), (3, 0.5), (10, 0.500001), (7, 0.42857)])
def test_rehashed_impossible_all_win_fraction_rejected(count, impossible):
    a, b = pair()
    b = receipt('b', 'd', count=count)
    b['all_exploratory']['gross_win_fraction'] = impossible
    rehash(b)
    with pytest.raises(ValueError, match='integer outcomes'):
        audit_m1_multi_archive_census([a, b])


def test_rehashed_feasible_but_partition_inconsistent_integer_wins_rejected():
    a, b = pair()
    b = receipt('b', 'd', count=10)
    # 5/10 is individually feasible but the original 7/3 splits have 3+1 wins.
    b['all_exploratory']['gross_win_fraction'] = 0.5
    rehash(b)
    with pytest.raises(ValueError, match='integer win counts'):
        audit_m1_multi_archive_census([a, b])


def test_valid_fraction_rounding_and_integer_partition_counts():
    a = receipt('a', 'c', count=7)
    b = receipt('b', 'd', count=13)
    assert a['later_exploratory_not_holdout']['gross_win_fraction'] == 0.333333
    assert a['all_exploratory']['gross_win_fraction'] == 0.428571
    assert audit_m1_multi_archive_census([a, b])['report_count'] == 2

def test_rehashed_bar_population_above_original_engine_limit_rejected():
    a, b = pair()
    b['bar_count'] = 500_001
    rehash(b)
    with pytest.raises(ValueError, match='bar count'):
        audit_m1_multi_archive_census([a, b])
