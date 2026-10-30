import pytest
from app.prospective_receipt_census import audit_declared_m1_receipts

T = 1790000040  # minute boundary
NOW = T + 240
KW = dict(provider='fixture', symbol='XAU/USD', venue='synthetic', price_side='BID',
          observed_at_utc=NOW)

def bar(t=T, **updates):
    x = dict(provider='fixture', symbol='XAU/USD', venue='synthetic', price_side='BID',
             bar_start_utc=t, received_at_utc=t+65, open=100., high=102., low=99., close=101.)
    x.update(updates)
    return x

def run(receipts=None, expected=None, **kw):
    return audit_declared_m1_receipts(receipts if receipts is not None else [bar(T), bar(T+60)],
                                     expected if expected is not None else [T,T+60], **(KW|kw))

def test_complete_is_still_unverified_and_not_live():
    result = run()
    assert result['status'] == 'INTERNAL_CENSUS_ONLY_NOT_LIVE'
    assert result['missing_expected_minutes'] == 0
    assert result['provider_entitlement_verified'] is False
    assert result['source_authenticated'] is False
    assert result['live'] is False and result['may_execute_order'] is False
    assert result['input_sha256'] == run()['input_sha256']

def test_missing_and_unexpected_are_distinct():
    x = run([bar(T),bar(T+120)], [T,T+60])
    assert (x['missing_expected_minutes'],x['unexpected_observed_minutes']) == (1,1)
    assert x['status'] == 'REVIEW_REQUIRED'
    assert len(x['missing_utc_samples']) == len(x['unexpected_utc_samples']) == 1

def test_duplicate_and_conflicting_prices_cannot_pass():
    x = run([bar(T),bar(T),bar(T+60)])
    assert (x['duplicate_receipt_rows'],x['conflicting_duplicate_rows']) == (1,0)
    assert x['status'] == 'REVIEW_REQUIRED'
    y = run([bar(T),bar(T,close=100.5),bar(T+60)])
    assert (y['duplicate_receipt_rows'],y['conflicting_duplicate_rows']) == (1,1)

def test_late_and_stale_are_separate_from_gap():
    x = run([bar(T,received_at_utc=T+200),bar(T+60)],max_receipt_lag_seconds=60)
    assert x['late_receipt_rows'] == 1
    assert x['status'] == 'REVIEW_REQUIRED'
    y = run([bar(T),bar(T+60)], observed_at_utc=NOW+200)
    assert y['stale_declared_observation'] is True
    assert y['missing_expected_minutes'] == 0

def test_no_receipts_is_not_success():
    x=run([])
    assert x['missing_expected_minutes']==2
    assert x['stale_declared_observation'] is True
    assert x['seconds_since_last_declared_receipt'] is None

@pytest.mark.parametrize('bad', [
    lambda r:r.update(provider='other'),
    lambda r:r.update(price_side='ASK'),
    lambda r:r.update(bar_start_utc=T+1),
    lambda r:r.update(received_at_utc=T+59),
    lambda r:r.update(received_at_utc=NOW+1),
    lambda r:r.update(open=float('nan')),
    lambda r:r.update(high=99),
    lambda r:r.update(open=True),
    lambda r:r.update(verified=True),
])
def test_invalid_receipts_fail_closed(bad):
    r=bar();bad(r)
    with pytest.raises(ValueError):run([r])

@pytest.mark.parametrize('expected', [[],[T,T],[T+60,T],[T+1],[T+240],[True]])
def test_unverified_or_invalid_calendar_fails_closed(expected):
    with pytest.raises(ValueError):run(expected=expected)

def test_bounds_and_no_implicit_substitution():
    with pytest.raises(ValueError):run(price_side='CFD')
    with pytest.raises(ValueError):run(sample_limit=51)
    with pytest.raises(ValueError):run(max_receipt_lag_seconds=-1)
    with pytest.raises(ValueError):run(receipts=[bar()]*10001)
    with pytest.raises(ValueError):run(expected=list(range(T,T+10001*60,60)))
    assert run(sample_limit=0, receipts=[bar(T)])['missing_utc_samples']==[]

def test_reordered_receipts_change_fingerprint_but_not_population():
    a=run()
    b=run([bar(T+60),bar(T)])
    assert a['input_sha256']!=b['input_sha256']
    assert a['unique_observed_minutes']==b['unique_observed_minutes']==2
