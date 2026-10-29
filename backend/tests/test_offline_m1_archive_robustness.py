"""Synthetic offline robustness tests; never validates real historical profits."""
import copy
import pytest

from app.offline_m1_archive_robustness import audit_m1_archive_robustness
from test_offline_m1_multi_archive_census import receipt, rehash


def sample():
    return [receipt('a', 'c', count=2, mean=0),
            receipt('b', 'd', count=8, mean=10),
            receipt('e', 'f', count=10, mean=-2)]


def test_trade_weighted_vs_archive_balanced_and_costs():
    result = audit_m1_archive_robustness(sample())
    g = result['groups'][0]
    assert g['evaluated_outcome_count'] == 20
    assert g['status'] == 'DESCRIPTIVE_ARCHIVE_STRESS_ONLY'
    s = g['scenarios_by_illustrative_cost_bps']
    assert s['0']['trade_weighted_net_bps'] == 3
    assert s['0']['equal_archive_net_bps'] == pytest.approx(8 / 3, abs=1e-6)
    assert s['5']['trade_weighted_net_bps'] == -2
    assert s['5']['archive_means_positive_after_cost'] == 1
    assert s['5']['worst_archive_net_bps'] == -7
    assert s['5']['best_archive_net_bps'] == 5
    assert s['5']['leave_one_archive_out_min_net_bps'] == -6.666667
    assert s['5']['leave_one_archive_out_max_net_bps'] == 3
    assert not result['trade_authorized'] and not result['verified_profitability']
    assert not result['statistical_significance_verified']


def test_order_invariance_and_source_binding():
    a = sample()
    assert audit_m1_archive_robustness(a) == audit_m1_archive_robustness(a[::-1])
    changed = copy.deepcopy(a)
    changed[0]['source']['provider'] = 'OtherVendor'
    rehash(changed[0])
    assert audit_m1_archive_robustness(changed)['research_sha256'] != audit_m1_archive_robustness(a)['research_sha256']
    assert len(audit_m1_archive_robustness(changed)['groups']) == 2


def test_single_archive_group_abstains_on_deletion():
    a = sample()[:2]
    a[1]['source']['instrument'] = 'XAUUSD'
    rehash(a[1])
    g = audit_m1_archive_robustness(a)['groups'][0]
    assert g['status'] == 'INSUFFICIENT_ARCHIVE_REPLICATION'
    assert g['scenarios_by_illustrative_cost_bps']['5']['leave_one_archive_out_max_net_bps'] is None


def test_empty_archive_not_treated_as_success():
    a = sample()[:2]
    a[0] = receipt('a', 'c', count=0)
    g = audit_m1_archive_robustness(a)['groups'][0]
    assert g['status'] == 'INCOMPLETE_ARCHIVE_COVERAGE'
    assert g['empty_archive_count'] == 1
    assert g['scenarios_by_illustrative_cost_bps']['0']['leave_one_archive_out_min_net_bps'] is None


def test_all_empty_means_are_unknown():
    a = [receipt('a', 'c', count=0), receipt('b', 'd', count=0)]
    g = audit_m1_archive_robustness(a)['groups'][0]
    assert g['status'] == 'NO_EVALUATED_ARCHIVES'
    assert g['scenarios_by_illustrative_cost_bps']['5']['trade_weighted_net_bps'] is None


def test_hash_tampering_fails_closed():
    a = sample()
    a[1]['all_exploratory']['mean_gross_bps'] = 20
    with pytest.raises(ValueError, match='fingerprint'):
        audit_m1_archive_robustness(a)


def test_duplicate_archive_fails_closed():
    a = sample()
    a[1]['source']['archive_sha256'] = a[0]['source']['archive_sha256']
    rehash(a[1])
    with pytest.raises(ValueError, match='Duplicate'):
        audit_m1_archive_robustness(a)


def test_oversized_count_fails_closed():
    a = sample()
    # Keep the upstream 70/30 partition internally consistent so the
    # downstream robustness-specific 500k outcome bound is actually tested.
    a[0] = receipt('a', 'c', count=500001, mean=0)
    a[0]['bar_count'] = 500002
    rehash(a[0])
    with pytest.raises(ValueError, match='bar count'):
        audit_m1_archive_robustness(a)


def test_unbounded_mean_fails_closed():
    a = sample()
    # Preserve upstream split-mean reconciliation to exercise this auditor's
    # independent implausible-mean rejection, not the earlier split guard.
    a[0] = receipt('a', 'c', count=2, mean=1_000_001)
    with pytest.raises(ValueError, match='Implausibly'):
        audit_m1_archive_robustness(a)


def test_rounded_receipt_not_raised_to_precision_claim():
    a = [receipt('a', 'c', count=2, mean=0.000001), receipt('b', 'd', count=2, mean=0.000002)]
    g = audit_m1_archive_robustness(a)['groups'][0]
    assert g['scenarios_by_illustrative_cost_bps']['0']['trade_weighted_net_bps'] == 0.000002
    assert 'rounded' in audit_m1_archive_robustness(a)['warning']


def test_cost_grid_is_not_broker_execution():
    x = audit_m1_archive_robustness(sample())
    assert x['cost_grid_bps'] == [0, 5, 10, 20]
    assert x['executable_quotes_verified'] is False
    assert x['protected_holdout'] is False

def test_incomplete_source_withholds_all_scenario_returns_and_success_counts():
    a = receipt('a', 'c', count=0)
    b = receipt('b', 'd', count=2, mean=50)
    c = receipt('e', 'f', count=2, mean=60)
    g = audit_m1_archive_robustness([a, b, c])['groups'][0]
    assert g['status'] == 'INCOMPLETE_ARCHIVE_COVERAGE'
    assert g['evaluated_outcome_count'] == 4
    assert g['evaluated_archive_count'] == 2
    for scenario in g['scenarios_by_illustrative_cost_bps'].values():
        assert all(value is None for value in scenario.values())


def test_complete_source_still_reports_after_another_source_is_incomplete():
    a = receipt('a', 'c', count=0)
    b = receipt('b', 'd', count=2, mean=50)
    c = receipt('e', 'f', count=2, mean=-2, instrument='XAUUSD')
    d = receipt('f', 'e', count=2, mean=-4, instrument='XAUUSD')
    groups = audit_m1_archive_robustness([a, b, c, d])['groups']
    assert groups[0]['scenarios_by_illustrative_cost_bps']['0']['trade_weighted_net_bps'] is None
    assert groups[1]['status'] == 'DESCRIPTIVE_ARCHIVE_STRESS_ONLY'
    assert groups[1]['scenarios_by_illustrative_cost_bps']['0']['trade_weighted_net_bps'] == -3
