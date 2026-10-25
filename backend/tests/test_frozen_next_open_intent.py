"""Synthetic causal-next-open protocol tests; no market archive or broker claims."""
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.frozen_next_open_intent import (
    audit_next_open_intents, fingerprint_next_open_intents,
)

T = int(datetime(2026, 1, 5, tzinfo=timezone.utc).timestamp())
SOURCE = dict(instrument='XAUUSD', provider='fixture', venue='fixture',
              archive_sha256='a'*64, price_side='BID', horizon_minutes=1)


def bar(at, open='100.25', high='101', low='99.5', close='100.5'):
    return dict(at=at, open=open, high=high, low=low, close=close)


def fixtures(n=36):
    intents, obs = [], []
    for i in range(n):
        t = T + i * 7 * 86400
        intents.append(dict(path_id=f'p{i}', signal_at=t, direction='LONG', stop='99', target='102'))
        obs.append(dict(path_id=f'p{i}', bars=[bar(t+60)]))
    return dict(protocol='frozen-next-open-intent-v1', source=deepcopy(SOURCE),
                eligible_intents=intents, excluded_signals=[]), obs


def run(m, obs, digest=None):
    return audit_next_open_intents(m, obs, digest or fingerprint_next_open_intents(m))


def test_causal_open_is_derived_from_observation_not_manifest():
    m, obs = fixtures()
    result = run(m, obs)
    assert 'entry' not in m['eligible_intents'][0]
    assert result['status'] == 'DESCRIPTIVE_BOUNDS_ONLY'
    assert result['paths'][0]['entry_observed'] == '100.25'
    assert result['paths'][0]['lower_gross_r'] == '0.2'
    assert result['future_open_preregistered'] is False
    assert result['verified_profitability'] is False
    assert len(result['cost_scenarios']) == 4


def test_missing_next_open_withholds_population_mean():
    m, obs = fixtures()
    obs[0]['bars'] = []
    r = run(m, obs)
    assert r['counts']['UNOBSERVED_NEXT_OPEN'] == 1
    assert r['status'] == 'UNRESOLVED_ENTRIES_OR_OUTCOMES'
    assert all(s['population_mean_lower_net_r'] is None for s in r['cost_scenarios'])


def test_late_first_observation_is_not_relabelled_as_next_open():
    m, obs = fixtures()
    m['source']['horizon_minutes'] = 2
    obs[0]['bars'] = [bar(T+120)]
    assert run(m, obs)['counts']['UNOBSERVED_NEXT_OPEN'] == 1


def test_open_gap_outside_frozen_bracket_is_unresolved_not_excluded():
    m, obs = fixtures()
    obs[0]['bars'] = [bar(T+60, open='103', high='104', low='102.5', close='103')]
    r = run(m, obs)
    assert r['counts']['GAPPED_BRACKET_UNRESOLVED'] == 1
    assert r['eligible_intents'] == 36
    assert r['cost_scenarios'][0]['population_mean_lower_net_r'] is None


def test_open_equal_stop_is_unresolved():
    m, obs = fixtures()
    obs[0]['bars'] = [bar(T+60, open='99', high='100', low='98', close='99')]
    assert run(m, obs)['counts']['GAPPED_BRACKET_UNRESOLVED'] == 1


def test_ambiguous_same_m1_touches_stay_bounded():
    m, obs = fixtures()
    obs[0]['bars'] = [bar(T+60, high='103', low='98')]
    r = run(m, obs)
    assert r['counts']['AMBIGUOUS'] == 1
    assert Decimal(r['paths'][0]['lower_gross_r']) < 0
    assert Decimal(r['paths'][0]['upper_gross_r']) > 0


def test_digest_detects_changed_frozen_stop_and_membership():
    m, obs = fixtures()
    digest = fingerprint_next_open_intents(m)
    m['eligible_intents'][0]['stop'] = '98'
    with pytest.raises(ValueError, match='SHA-256 mismatch'):
        run(m, obs, digest)


def test_cannot_supply_future_entry_in_intent_or_outcome():
    m, obs = fixtures()
    m['eligible_intents'][0]['entry'] = '100.25'
    with pytest.raises(ValueError, match='exactly'):
        run(m, obs)
    m, obs = fixtures()
    obs[0]['entry'] = '100.25'
    with pytest.raises(ValueError, match='exactly'):
        run(m, obs)


def test_missing_duplicate_extra_observations_fail_closed():
    m, obs = fixtures()
    with pytest.raises(ValueError, match='Incomplete'):
        run(m, obs[:-1])
    with pytest.raises(ValueError, match='Duplicate'):
        run(m, obs[:-1] + [deepcopy(obs[0])])
    with pytest.raises(ValueError, match='unregistered'):
        run(m, obs[:-1] + [dict(path_id='alien', bars=[])])


def test_malformed_ohlc_and_clock_rejected_even_after_first_bar():
    m, obs = fixtures()
    obs[0]['bars'][0]['high'] = '99'
    with pytest.raises(ValueError, match='OHLC'):
        run(m, obs)
    m, obs = fixtures()
    obs[0]['bars'][0]['at'] = T
    with pytest.raises(ValueError, match='pre-entry'):
        run(m, obs)


def test_declared_exclusion_withholds_population_mean():
    m, obs = fixtures()
    m['excluded_signals'].append(dict(path_id='excluded', signal_at=T+40*7*86400,
                                      reason='PRE_SIGNAL_DATA_GAP'))
    r = run(m, obs)
    assert r['status'] == 'UNVERIFIED_EXCLUSIONS'
    assert r['declared_excluded_signals'] == 1
    assert r['cost_scenarios'][0]['population_mean_lower_net_r'] is None


def test_censored_horizon_withholds_full_population_mean():
    m, obs = fixtures()
    m['source']['horizon_minutes'] = 2
    r = run(m, obs)
    assert r['counts']['CENSORED'] == 36
    assert r['status'] == 'UNRESOLVED_ENTRIES_OR_OUTCOMES'


def test_negative_prices_supported_and_zero_open_unresolved():
    m, obs = fixtures(1)
    m['eligible_intents'][0].update(stop='-37', target='-31')
    obs[0]['bars'] = [bar(T+60, open='-35', high='-34', low='-36', close='-34')]
    assert run(m, obs)['paths'][0]['status'] == 'DETERMINATE'
    m, obs = fixtures(1)
    m['eligible_intents'][0].update(stop='-1', target='2')
    obs[0]['bars'] = [bar(T+60, open='0', high='1', low='-1', close='0')]
    assert run(m, obs)['counts']['GAPPED_BRACKET_UNRESOLVED'] == 1


def test_small_sample_no_population_claim():
    m, obs = fixtures(1)
    assert run(m, obs)['status'] == 'INSUFFICIENT_SAMPLE'


def test_order_independent_digest_and_report():
    m, obs = fixtures()
    d = fingerprint_next_open_intents(m)
    m['eligible_intents'].reverse()
    obs.reverse()
    assert fingerprint_next_open_intents(m) == d
    assert run(m, obs, d)['paths'][0]['path_id'] == 'p0'
