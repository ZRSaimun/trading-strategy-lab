"""Synthetic-only fail-closed session/quote checks; no broker calls."""
from copy import deepcopy
import pytest
from app.paper_market_session_guard import review_paper_market_session

NOW = 1_800_000_000_000
SRC = dict(account_alias='paper-account-1', provider='TEST', venue='TEST', instrument='TEST-ETF')


def event(*, quote=False, previous=False, **changes):
    data = dict(SRC, observed_ms=NOW - (900 if previous else 300),
                received_ms=NOW - (800 if previous else 200),
                sequence=12 if previous else 13,
                event_id='evt-previous-01' if previous else 'evt-current-001')
    if quote:
        data.update(bid='100', ask='100.02')
        data['event_id'] += '-quote'
    else:
        data['status'] = 'OPEN'
    data.update(changes)
    return data


def run(session=None, quote=None, previous_session=None, previous_quote=None, **kwargs):
    return review_paper_market_session(SRC, session or event(), quote or event(quote=True),
                                       now_ms=NOW,
                                       previous_session=previous_session if previous_session is not None else event(previous=True),
                                       previous_quote=previous_quote if previous_quote is not None else event(quote=True, previous=True),
                                       **kwargs)


def test_open_declared_session_never_grants_permission():
    result = run()
    assert result['assumption_checks_pass']
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False
    assert result['quote_authenticated'] is False and result['session_authenticated'] is False


@pytest.mark.parametrize('status', ['HALTED', 'CLOSED', 'AUCTION', 'PREOPEN', 'POSTMARKET', 'UNKNOWN'])
def test_closed_or_special_market_state_blocks(status):
    assert 'session_open' in run(session=event(status=status))['failed_checks']


@pytest.mark.parametrize('changes,failed', [
    ({'observed_ms': NOW-20_000}, 'session_fresh'),
    ({'received_ms': NOW+1}, 'session_time_order'),
    ({'received_ms': NOW-100, 'observed_ms': NOW-2000}, 'session_transport_ok'),
    ({'sequence': 12}, 'session_sequence_contiguous'),
    ({'sequence': 15}, 'session_sequence_contiguous'),
    ({'event_id': 'evt-previous-01'}, 'session_not_replayed'),
    ({'observed_ms': NOW-1000}, 'session_not_replayed'),
])
def test_session_event_failures(changes, failed):
    assert failed in run(session=event(**changes))['failed_checks']


@pytest.mark.parametrize('changes,failed', [
    ({'observed_ms': NOW-5000}, 'quote_fresh'),
    ({'received_ms': NOW+1}, 'quote_time_order'),
    ({'received_ms': NOW-100, 'observed_ms': NOW-2000}, 'quote_transport_ok'),
    ({'sequence': 12}, 'quote_sequence_contiguous'),
    ({'sequence': 15}, 'quote_sequence_contiguous'),
    ({'event_id': 'evt-previous-01-quote'}, 'quote_not_replayed'),
    ({'bid': '100.05'}, 'uncrossed_quote'),
    ({'ask': '105'}, 'spread_within_cap'),
    ({'observed_ms': NOW-500}, 'quote_after_session_event'),
])
def test_quote_event_failures(changes, failed):
    assert failed in run(quote=event(quote=True, **changes))['failed_checks']


def test_missing_checkpoint_fails_closed():
    result = review_paper_market_session(SRC, event(), event(quote=True), now_ms=NOW)
    assert 'complete_prior_checkpoint' in result['failed_checks']
    assert not result['assumption_checks_pass']


def test_partial_checkpoint_rejected():
    with pytest.raises(ValueError, match='Partial previous checkpoint'):
        review_paper_market_session(SRC, event(), event(quote=True),
                                    now_ms=NOW, previous_session=event(previous=True))


@pytest.mark.parametrize('bad', [True, 2.0, -1, 8_640_000_000_000_001])
def test_bad_server_clock_rejected(bad):
    with pytest.raises(ValueError):
        review_paper_market_session(SRC, event(), event(quote=True), now_ms=bad)


@pytest.mark.parametrize('bad', ['1e2', 'NaN', 'Infinity', '0', '-1', ' 100', '1.000000001', 100.0, True])
def test_bad_price_rejected(bad):
    with pytest.raises(ValueError):
        run(quote=event(quote=True, bid=bad))


@pytest.mark.parametrize('bad', ['bad-status', '', 1, True])
def test_bad_status_rejected(bad):
    with pytest.raises(ValueError):
        run(session=event(status=bad))


def test_source_mismatch_and_extra_fields_rejected():
    with pytest.raises(ValueError):
        run(quote=event(quote=True, provider='OTHER'))
    with pytest.raises(ValueError):
        run(session=event(secret='no'))


def test_timing_caps_cannot_be_disabled():
    for policy in [dict(max_quote_age_ms=60000), dict(max_session_age_ms=60000),
                   dict(max_transport_lag_ms=60000), dict(max_spread_bps='10001'),
                   dict(max_quote_age_ms=True)]:
        with pytest.raises(ValueError):
            run(**policy)


def test_review_digest_binds_complete_state_and_is_deterministic():
    a = run()
    assert a == run()
    assert a['review_sha256'] != run(quote=event(quote=True, ask='100.03'))['review_sha256']
    assert a['review_sha256'] != run(session=event(status='HALTED'))['review_sha256']
    assert a['review_sha256'] != run(max_spread_bps='26')['review_sha256']


def test_no_input_mutation():
    src, s, q, ps, pq = deepcopy(SRC), event(), event(quote=True), event(previous=True), event(quote=True, previous=True)
    originals = deepcopy((src, s, q, ps, pq))
    review_paper_market_session(src, s, q, now_ms=NOW, previous_session=ps, previous_quote=pq)
    assert (src, s, q, ps, pq) == originals


def test_previous_future_event_fails_closed():
    result = run(previous_session=event(previous=True, received_ms=NOW+1))
    assert 'previous_events_not_future' in result['failed_checks']


@pytest.mark.parametrize('prior_session,prior_quote,failed', [
    ({'observed_ms': NOW - 700}, {}, 'previous_session_time_order'),
    ({}, {'observed_ms': NOW - 700}, 'previous_quote_time_order'),
    ({'observed_ms': NOW - 2500}, {}, 'previous_session_transport_ok'),
    ({}, {'observed_ms': NOW - 2500}, 'previous_quote_transport_ok'),
    ({}, {'bid': '100.02'}, 'previous_quote_uncrossed'),
    ({}, {'ask': '105'}, 'previous_spread_within_cap'),
    ({'observed_ms': NOW - 600}, {}, 'previous_quote_after_session_event'),
])
def test_prior_checkpoint_must_have_valid_time_and_price_envelope(
        prior_session, prior_quote, failed):
    result = run(
        previous_session=event(previous=True, **prior_session),
        previous_quote=event(quote=True, previous=True, **prior_quote))
    assert failed in result['failed_checks']
    assert result['assumption_checks_pass'] is False
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False


def test_prior_checkpoint_envelope_passes_for_normal_synthetic_events():
    result = run()
    for check in (
        'previous_session_time_order', 'previous_quote_time_order',
        'previous_session_transport_ok', 'previous_quote_transport_ok',
        'previous_quote_after_session_event', 'previous_quote_uncrossed',
        'previous_spread_within_cap',
    ):
        assert result['checks'][check] is True
    assert result['assumption_checks_pass'] is True


def test_prior_quote_price_change_is_bound_to_review_digest():
    original = run()
    changed = run(previous_quote=event(quote=True, previous=True, ask='100.03'))
    assert changed['assumption_checks_pass']
    assert original['review_sha256'] != changed['review_sha256']
    assert changed['may_execute_real_order'] is False
