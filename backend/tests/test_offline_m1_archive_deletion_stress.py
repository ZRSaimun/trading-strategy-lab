"""Synthetic-only tests for source-local whole-archive deletion sensitivity."""
import copy
from itertools import combinations

import pytest

from app.offline_m1_archive_deletion_stress import audit_m1_archive_deletion_stress
from test_offline_m1_multi_archive_census import receipt, rehash


def sample():
    return [receipt('a', 'c', count=2, mean=0),
            receipt('b', 'd', count=8, mean=10),
            receipt('e', 'f', count=10, mean=-2),
            receipt('1', '2', count=4, mean=4)]


def test_exact_whole_archive_deletion_extrema():
    g = audit_m1_archive_deletion_stress(sample())['groups'][0]
    assert g['status'] == 'DESCRIPTIVE_DELETION_STRESS_ONLY'
    assert g['evaluated_outcome_count'] == 24
    for k in (1, 2, 3):
        stress = g['deletion_by_whole_archive_count'][str(k)]
        assert stress['evaluated_combinations'] == {1: 4, 2: 6, 3: 4}[k]
        values = [(2, 0), (8, 10), (10, -2), (4, 4)]
        survivors = []
        for removed in combinations(range(4), k):
            remaining = [v for i, v in enumerate(values) if i not in removed]
            survivors.append(sum(n * gross for n, gross in remaining) / sum(n for n, _ in remaining))
        for cost in (0, 5, 10, 20):
            scenario = stress['scenarios_by_illustrative_cost_bps'][str(cost)]
            assert scenario['min_net_bps'] == pytest.approx(min(survivors) - cost, abs=1e-6)
            assert scenario['max_net_bps'] == pytest.approx(max(survivors) - cost, abs=1e-6)


def test_input_order_invariance_and_source_binding():
    reports = sample()
    assert audit_m1_archive_deletion_stress(reports) == audit_m1_archive_deletion_stress(reports[::-1])
    changed = copy.deepcopy(reports)
    changed[0]['source']['instrument'] = 'XAUUSD'
    rehash(changed[0])
    x = audit_m1_archive_deletion_stress(changed)
    assert len(x['groups']) == 2
    assert x['research_sha256'] != audit_m1_archive_deletion_stress(reports)['research_sha256']
    assert x['groups'][1]['status'] == 'INSUFFICIENT_ARCHIVE_REPLICATION'


def test_empty_archive_withholds_all_stress():
    reports = sample()
    reports[0] = receipt('a', 'c', count=0)
    g = audit_m1_archive_deletion_stress(reports)['groups'][0]
    assert g['status'] == 'INCOMPLETE_ARCHIVE_COVERAGE'
    for stress in g['deletion_by_whole_archive_count'].values():
        assert stress['evaluated_combinations'] == 0
        assert all(s['min_net_bps'] is None and s['max_net_bps'] is None
                   for s in stress['scenarios_by_illustrative_cost_bps'].values())


def test_two_archive_group_abstains_on_deleting_both():
    g = audit_m1_archive_deletion_stress(sample()[:2])['groups'][0]
    assert g['deletion_by_whole_archive_count']['1']['evaluated_combinations'] == 2
    assert g['deletion_by_whole_archive_count']['2']['evaluated_combinations'] == 0
    assert g['deletion_by_whole_archive_count']['3']['evaluated_combinations'] == 0


def test_self_rehashed_duplicate_and_invalid_inputs_rejected():
    reports = sample()
    reports[1]['source']['archive_sha256'] = reports[0]['source']['archive_sha256']
    rehash(reports[1])
    with pytest.raises(ValueError, match='Duplicate'):
        audit_m1_archive_deletion_stress(reports)
    with pytest.raises(ValueError):
        audit_m1_archive_deletion_stress(iter(sample()))


def test_no_statistical_or_execution_authorization():
    result = audit_m1_archive_deletion_stress(sample())
    assert result['cost_grid_bps'] == [0, 5, 10, 20]
    assert result['max_removed_archives'] == 3
    for key in ('trade_authorized', 'verified_profitability', 'protected_holdout',
                'executable_quotes_verified', 'source_authenticity_verified',
                'statistical_significance_verified'):
        assert result[key] is False
