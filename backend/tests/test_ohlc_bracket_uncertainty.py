from datetime import datetime, timezone, timedelta
import pytest
from app.ohlc_bracket_uncertainty import evaluate_path, audit_paths

T = 1760313600  # UTC-aligned minute

def bar(at=T+60, o='100', h='100.5', l='99.5', c='100'):
    return dict(at=at, open=o, high=h, low=l, close=c)

def path(**changes):
    p = dict(path_id='p', instrument='NSXUSD-CFD', provider='fixture', venue='proxy',
             archive_sha256='a'*64, price_side='BID', direction='LONG',
             signal_at=T, entry_at=T+60, entry='100', stop='99', target='102',
             horizon_minutes=1, bars=[bar()])
    p.update(changes)
    return p

def test_horizon_close_and_costs():
    r = evaluate_path(path(bars=[bar(c='100.5')]))
    assert r['status'] == 'DETERMINATE'
    assert r['lower_gross_r'] == '0.5'
    assert r['cost_scenarios'][1]['lower_net_r'] == '0.45'

def test_both_touched_is_bounded_not_winning():
    r = evaluate_path(path(bars=[bar(h='102', l='99')]))
    assert r['status'] == 'AMBIGUOUS'
    assert r['lower_gross_r'] == '-1'
    assert r['upper_gross_r'] == '2'
    assert r['cost_scenarios'][3]['lower_net_r'] == '-1.2'

def test_stop_and_target_first_touch():
    assert evaluate_path(path(bars=[bar(l='98.5')]))['lower_gross_r'] == '-1'
    assert evaluate_path(path(bars=[bar(h='103')]))['lower_gross_r'] == '2'

def test_adverse_gap_open_worse_than_stop():
    p = path(horizon_minutes=2, bars=[bar(), bar(T+120, o='98', h='99', l='97', c='98')])
    assert evaluate_path(p)['lower_gross_r'] == '-2'

def test_favourable_gap_capped_at_target():
    p = path(horizon_minutes=2, bars=[bar(), bar(T+120, o='104', h='105', l='103', c='104')])
    assert evaluate_path(p)['lower_gross_r'] == '2'

def test_short_direction_and_ambiguous_order():
    p = path(direction='SHORT', stop='101', target='98', bars=[bar(h='101', l='98')])
    r = evaluate_path(p)
    assert r['status'] == 'AMBIGUOUS'
    assert r['lower_gross_r'] == '-1' and r['upper_gross_r'] == '2'

def test_missing_or_gapped_censored_not_flat():
    assert evaluate_path(path(bars=[]))['status'] == 'CENSORED'
    p = path(horizon_minutes=2, bars=[bar(), bar(T+180)])
    r = evaluate_path(p)
    assert r['status'] == 'CENSORED' and r['lower_gross_r'] is None

def test_rejects_entry_not_next_open():
    with pytest.raises(ValueError, match='next UTC minute'):
        evaluate_path(path(entry_at=T+120))
    with pytest.raises(ValueError, match='next-open'):
        evaluate_path(path(bars=[bar(o='100.1', h='101')]))

def test_rejects_ohlc_corruption_and_nonmonotonic():
    with pytest.raises(ValueError, match='OHLC'):
        evaluate_path(path(bars=[bar(h='99')]))
    with pytest.raises(ValueError, match='Nonmonotonic'):
        evaluate_path(path(horizon_minutes=2, bars=[bar(), bar(T+60)]))

def test_rejects_source_and_price_tampering():
    with pytest.raises(ValueError, match='SHA'):
        evaluate_path(path(archive_sha256='bad'))
    with pytest.raises(ValueError, match='decimal'):
        evaluate_path(path(entry='nan'))
    with pytest.raises(ValueError, match='strictly'):
        evaluate_path(path(stop='101'))

def test_negative_oil_prices_supported():
    p = path(instrument='WTI-202005', entry='-35', stop='-37', target='-31',
             bars=[bar(o='-35', h='-34', l='-36', c='-34')])
    assert evaluate_path(p)['lower_gross_r'] == '0.5'

def test_insufficient_sample_withholds_mean():
    a = audit_paths([path()])
    assert a['status'] == 'INSUFFICIENT_OR_CENSORED'
    assert a['cost_scenarios'][0]['population_mean_lower_net_r'] is None

def test_full_sample_reports_bounds_only():
    base = datetime(2026, 1, 5, tzinfo=timezone.utc)
    ps=[]
    for i in range(36):
        t=int((base+timedelta(weeks=i)).timestamp())
        ps.append(path(path_id=f'p{i}',signal_at=t,entry_at=t+60,bars=[bar(t+60,h='102',l='99')]))
    a=audit_paths(ps)
    assert a['status']=='DESCRIPTIVE_BOUNDS_ONLY'
    assert a['counts']['AMBIGUOUS']==36
    assert a['cost_scenarios'][0]['population_mean_lower_net_r']=='-1'
    assert a['cost_scenarios'][0]['population_mean_upper_net_r']=='2'
    assert a['verified_profitability'] is False

def test_censored_sample_never_reports_survivor_mean():
    base = datetime(2026, 1, 5, tzinfo=timezone.utc)
    ps=[]
    for i in range(36):
        t=int((base+timedelta(weeks=i)).timestamp())
        ps.append(path(path_id=f'p{i}',signal_at=t,entry_at=t+60,bars=[bar(t+60)] if i else []))
    a=audit_paths(ps)
    assert a['counts']['CENSORED']==1
    assert a['cost_scenarios'][0]['population_mean_lower_net_r'] is None

def test_duplicate_and_mixed_source_rejected():
    with pytest.raises(ValueError,match='Duplicate'):
        audit_paths([path(),path()])
    with pytest.raises(ValueError,match='Mixed source'):
        audit_paths([path(),path(path_id='q',provider='other',signal_at=T+60,entry_at=T+120,bars=[bar(T+120)])])

def test_duplicate_signal_clock_and_mixed_horizons_rejected():
    with pytest.raises(ValueError,match='Duplicate completed-signal'):
        audit_paths([path(),path(path_id='q')])
    with pytest.raises(ValueError,match='Mixed source'):
        audit_paths([path(),path(path_id='q',signal_at=T+60,entry_at=T+120,
                                 horizon_minutes=2,bars=[bar(T+120),bar(T+180)])])
