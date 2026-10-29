"""Synthetic aggregation checks: never claims actual vendor authentication."""
import hashlib
import json
import pytest
from app.offline_m1_multi_archive_census import audit_m1_multi_archive_census, BODY_KEYS, POLICY


def receipt(archive='a', manifest='c', count=2, mean=1.0, instrument='NSXUSD'):
    s = {'count': count, 'mean_gross_bps': mean if count else None,
         'mean_net_bps_by_roundtrip_cost': {str(c): round(mean-c, 6) if count else None for c in (0, 5, 10, 20)},
         'gross_win_fraction': 0.5 if count else None}
    empty = {'count': 0, 'mean_gross_bps': None,
             'mean_net_bps_by_roundtrip_cost': {str(c): None for c in (0, 5, 10, 20)},
             'gross_win_fraction': None}
    r = {'policy': POLICY, 'source': {'instrument': instrument, 'provider': 'HistData',
          'archive_sha256': archive*64, 'price_side': 'UNVERIFIED_SINGLE_SIDE',
          'time_convention': 'SOURCE_WALL_UNVERIFIED'},
         'bar_count': 100, 'bar_manifest_sha256': manifest*64,
         'timestamp_discontinuities': 0, 'backward_jumps': 0, 'adjacent_duplicates': 0,
         'sweep_count': count, 'ambiguous_count': 0, 'confirmed_count': count,
         'censored_gap_or_end': 0, 'excluded_overlap': 0, 'horizon_minutes': 15,
         'roundtrip_cost_bps': [0, 5, 10, 20],
         'development_exploratory': empty, 'later_exploratory_not_holdout': empty,
         'all_exploratory': s, 'research_schema_version': 1, 'research_only': True,
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
