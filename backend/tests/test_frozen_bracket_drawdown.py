"""Synthetic-only tests; none represent observed trading performance."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.frozen_bracket_drawdown import summarize_frozen_drawdown, audit_frozen_bracket_drawdown
from app.frozen_bracket_population import fingerprint_population_manifest


BASE = datetime(2026, 1, 5, tzinfo=timezone.utc)
SOURCE = dict(instrument='NSXUSD-CFD', provider='synthetic', venue='synthetic',
              archive_sha256='a' * 64, price_side='BID', horizon_minutes=1)


def fixtures(n=36):
    eligible, paths = [], []
    for i in range(n):
        t = int((BASE + timedelta(weeks=i)).timestamp())
        frozen = dict(path_id=f'p{i}', signal_at=t, direction='LONG',
                      entry='100', stop='99', target='102')
        eligible.append(frozen)
        # Each week: -0.5R when horizon closes at 99.5; synthetic loss.
        paths.append(dict(**SOURCE, **frozen, entry_at=t + 60,
                          bars=[dict(at=t + 60, open='100', high='100.5',
                                     low='99.5', close='99.5')]))
    manifest = dict(protocol='m1-bracket-population-v1', source=deepcopy(SOURCE),
                    eligible_signals=eligible, excluded_signals=[])
    return manifest, paths


def run(m, p):
    return audit_frozen_bracket_drawdown(m, p, fingerprint_population_manifest(m))


def test_full_population_worst_case_drawdown_and_fixed_costs():
    m, p = fixtures()
    report = run(m, p)
    assert report['status'] == 'DESCRIPTIVE_WORST_CASE_BOUNDS_ONLY'
    assert [s['additional_round_trip_bps'] for s in report['cost_scenarios']] == [0, 5, 10, 20]
    assert report['cost_scenarios'][0]['maximum_possible_additive_drawdown_r'] == '18.0'
    assert report['cost_scenarios'][0]['all_upper_path_drawdown_r'] == '18.0'
    assert report['cost_scenarios'][1]['maximum_possible_additive_drawdown_r'] == '19.80'
    assert report['verified_profitability'] is False
    assert report['executable_broker_fills'] is False


def test_intrabar_ambiguity_uses_adverse_lower_bound():
    m, p = fixtures()
    p[0]['bars'][0] = dict(at=p[0]['entry_at'], open='100', high='103', low='98', close='100')
    report = run(m, p)
    s = report['cost_scenarios'][0]
    assert s['maximum_possible_additive_drawdown_r'] == '18.5'
    assert s['all_upper_path_drawdown_r'] == '17.5'
    assert s['total_lower_net_r'] == '-18.5'
    assert s['total_upper_net_r'] == '-15.5'


def test_out_of_order_inputs_produce_same_chronological_stress():
    m, p = fixtures()
    original = run(m, p)
    m['eligible_signals'].reverse()
    p.reverse()
    assert run(m, p) == original


def test_excluded_signal_withholds_entire_drawdown():
    m, p = fixtures()
    t = int((BASE + timedelta(weeks=40)).timestamp())
    m['excluded_signals'] = [dict(path_id='q', signal_at=t, reason='PRE_SIGNAL_DATA_GAP')]
    assert run(m, p)['status'] == 'WITHHELD_INCOMPLETE_OR_INSUFFICIENT'


def test_censored_outcome_withholds_entire_drawdown():
    m, p = fixtures()
    p[0]['bars'] = []
    assert run(m, p)['cost_scenarios'] == []


def test_insufficient_time_dispersion_withholds():
    m, p = fixtures(11)
    assert run(m, p)['status'] == 'WITHHELD_INCOMPLETE_OR_INSUFFICIENT'


def test_external_frozen_digest_required():
    m, p = fixtures()
    with pytest.raises(ValueError, match='SHA-256'):
        audit_frozen_bracket_drawdown(m, p, 'a' * 64)


def test_rejects_tampered_costs_and_inverted_bounds():
    m, p = fixtures()
    from app.frozen_bracket_population import audit_frozen_bracket_population
    result = audit_frozen_bracket_population(m, p, fingerprint_population_manifest(m))
    result['outcome_audit']['paths'][0]['cost_scenarios'][0]['lower_net_r'] = 'NaN'
    with pytest.raises(ValueError, match='Nonfinite'):
        summarize_frozen_drawdown(result)
    result = audit_frozen_bracket_population(m, p, fingerprint_population_manifest(m))
    result['outcome_audit']['paths'][0]['cost_scenarios'][0]['lower_net_r'] = '10'
    with pytest.raises(ValueError, match='Inverted'):
        summarize_frozen_drawdown(result)


def test_rejects_missing_population_completeness():
    m, p = fixtures()
    from app.frozen_bracket_population import audit_frozen_bracket_population
    result = audit_frozen_bracket_population(m, p, fingerprint_population_manifest(m))
    result['complete_against_supplied_manifest'] = False
    with pytest.raises(ValueError, match='completeness'):
        summarize_frozen_drawdown(result)


def test_rejects_per_path_cost_identity_change():
    m, p = fixtures()
    from app.frozen_bracket_population import audit_frozen_bracket_population
    result = audit_frozen_bracket_population(m, p, fingerprint_population_manifest(m))
    result['outcome_audit']['paths'][0]['cost_scenarios'][0]['additional_round_trip_bps'] = 1
    with pytest.raises(ValueError, match='Per-path cost'):
        summarize_frozen_drawdown(result)
