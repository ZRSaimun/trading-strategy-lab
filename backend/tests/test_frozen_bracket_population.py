"""Synthetic only; no historical source or broker price assertions."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import pytest

from app.frozen_bracket_population import (
    audit_frozen_bracket_population, fingerprint_population_manifest,
)

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
        paths.append(dict(**SOURCE, **frozen, entry_at=t + 60,
                          bars=[dict(at=t + 60, open='100', high='101',
                                     low='99.5', close='100.5')]))
    return dict(protocol='m1-bracket-population-v1', source=deepcopy(SOURCE),
                eligible_signals=eligible, excluded_signals=[]), paths


def run(manifest, paths, digest=None):
    return audit_frozen_bracket_population(
        manifest, paths, digest if digest is not None else fingerprint_population_manifest(manifest))


def test_full_population_allows_descriptive_bounds_but_not_profit_claim():
    m, p = fixtures()
    result = run(m, p)
    assert result['complete_against_supplied_manifest'] is True
    assert result['externally_preregistered'] is False
    assert result['source_rights_and_utc_verified'] is False
    assert result['verified_profitability'] is False
    assert result['outcome_audit']['status'] == 'DESCRIPTIVE_BOUNDS_ONLY'
    assert result['outcome_audit']['cost_scenarios'][0]['population_mean_lower_net_r'] == '0.5'


def test_input_order_does_not_change_digest_or_result():
    m, p = fixtures()
    digest = fingerprint_population_manifest(m)
    m['eligible_signals'].reverse()
    p.reverse()
    assert fingerprint_population_manifest(m) == digest
    assert run(m, p, digest)['outcome_audit']['paths'][0]['path_id'] == 'p0'


def test_tampered_eligibility_is_detected_by_external_digest():
    m, p = fixtures()
    digest = fingerprint_population_manifest(m)
    m['eligible_signals'][0]['stop'] = '98'
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        run(m, p, digest)


def test_missing_or_extra_outcome_is_rejected_not_survivor_filtered():
    m, p = fixtures()
    with pytest.raises(ValueError, match='Incomplete'):
        run(m, p[:-1])
    with pytest.raises(ValueError, match='Incomplete'):
        run(m, p + [deepcopy(p[0])])


def test_duplicate_and_unregistered_outcome_rejected():
    m, p = fixtures()
    q = deepcopy(p)
    q[-1] = deepcopy(q[0])
    with pytest.raises(ValueError, match='Duplicate or unregistered'):
        run(m, q)
    q = deepcopy(p)
    q[-1]['path_id'] = 'unknown'
    with pytest.raises(ValueError, match='Duplicate or unregistered'):
        run(m, q)


def test_price_direction_and_signal_clock_cannot_change_after_freeze():
    for key, changed in [('stop', '98'), ('target', '103'), ('direction', 'SHORT'),
                         ('signal_at', int(BASE.timestamp()) + 60)]:
        m, p = fixtures()
        p[0][key] = changed
        with pytest.raises(ValueError, match='modified frozen field'):
            run(m, p)


def test_source_and_entry_clock_cannot_change():
    m, p = fixtures()
    p[0]['price_side'] = 'ASK'
    with pytest.raises(ValueError, match='changed frozen source'):
        run(m, p)
    m, p = fixtures()
    p[0]['entry_at'] += 60
    with pytest.raises(ValueError, match='next-minute entry'):
        run(m, p)


def test_exclusions_are_counted_and_means_withheld():
    m, p = fixtures()
    t = int((BASE + timedelta(weeks=40)).timestamp())
    m['excluded_signals'].append(dict(path_id='excluded1', signal_at=t,
                                      reason='PRE_SIGNAL_DATA_GAP'))
    result = run(m, p)
    assert result['declared_excluded_signals'] == 1
    assert result['excluded_by_reason']['PRE_SIGNAL_DATA_GAP'] == 1
    assert result['outcome_audit']['status'] == 'UNVERIFIED_EXCLUSIONS'
    assert all(s['population_mean_lower_net_r'] is None for s in result['outcome_audit']['cost_scenarios'])


def test_exclusion_reason_and_membership_affect_digest():
    m, _ = fixtures()
    t = int((BASE + timedelta(weeks=40)).timestamp())
    m['excluded_signals'] = [dict(path_id='excluded1', signal_at=t, reason='PRE_SIGNAL_DATA_GAP')]
    before = fingerprint_population_manifest(m)
    m['excluded_signals'][0]['reason'] = 'INVALID_PRE_SIGNAL_CONTEXT'
    assert fingerprint_population_manifest(m) != before


def test_rejects_duplicate_clocks_across_eligible_and_excluded():
    m, _ = fixtures()
    m['excluded_signals'] = [dict(path_id='q', signal_at=m['eligible_signals'][0]['signal_at'],
                                  reason='PRE_SIGNAL_DATA_GAP')]
    with pytest.raises(ValueError, match='Duplicate'):
        fingerprint_population_manifest(m)


def test_rejects_unknown_exclusion_and_outcome_based_exclusion():
    m, _ = fixtures()
    m['excluded_signals'] = [dict(path_id='q', signal_at=int((BASE+timedelta(weeks=40)).timestamp()),
                                  reason='LOST_TRADE')]
    with pytest.raises(ValueError, match='Unrecognized'):
        fingerprint_population_manifest(m)


def test_rejects_extra_fields_and_invalid_frozen_prices():
    m, _ = fixtures()
    m['eligible_signals'][0]['future_return_r'] = '2'
    with pytest.raises(ValueError, match='exactly'):
        fingerprint_population_manifest(m)
    m, _ = fixtures()
    m['eligible_signals'][0]['entry'] = 'NaN'
    with pytest.raises(ValueError, match='decimal'):
        fingerprint_population_manifest(m)


def test_rejects_invalid_expected_digest():
    m, p = fixtures()
    with pytest.raises(ValueError, match='External expected'):
        run(m, p, 'not-a-digest')


def test_censored_outcome_is_not_silently_removed():
    m, p = fixtures()
    p[0]['bars'] = []
    result = run(m, p)
    assert result['outcome_audit']['counts']['CENSORED'] == 1
    assert result['outcome_audit']['status'] == 'INSUFFICIENT_OR_CENSORED'
    assert result['outcome_audit']['cost_scenarios'][0]['population_mean_lower_net_r'] is None


def test_rejects_frozen_manifest_changes_after_digest():
    m, p = fixtures()
    digest = fingerprint_population_manifest(m)
    m['source']['archive_sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        run(m, p, digest)
