"""Synthetic, no-network paper/broker snapshot safety regressions."""
from copy import deepcopy
import pytest
from app.paper_broker_snapshot_guard import evaluate_snapshot

NOW = 1_800_000_000_000


def inputs():
    expected = {
        'broker': 'Trading212-Invest', 'account_alias': 'paper1',
        'provider': 'DemoSource', 'venue': 'SIM',
        'positions': [{'instrument': 'ABC', 'side': 'LONG', 'quantity': '2',
                       'entry': '100', 'stop': '95', 'stress_exit': '90', 'point_value': '1'}],
        'max_quote_age_ms': 3000, 'max_transport_lag_ms': 1000,
        'max_spread_bps': '20', 'max_position_loss_cash': '30',
        'max_daily_loss_cash': '100', 'max_gross_leverage': '2',
        'max_margin_fraction': '1', 'previous_snapshot_id': 'prev',
        'previous_sequence': 1, 'previous_observed_at_ms': NOW - 3000,
        'circuit_latched': False,
    }
    observed = {
        'broker': 'Trading212-Invest', 'account_alias': 'paper1',
        'snapshot_id': 'next', 'sequence': 2, 'observed_at_ms': NOW - 500,
        'received_at_ms': NOW - 100, 'equity': '1000', 'used_margin': '200',
        'daily_realized_pnl': '0',
        'positions': [{'instrument': 'ABC', 'side': 'LONG', 'quantity': '2'}],
        'quotes': [{'instrument': 'ABC', 'provider': 'DemoSource', 'venue': 'SIM',
                    'quote_id': 'q1', 'bid': '100', 'ask': '100.1',
                    'observed_at_ms': NOW - 500, 'received_at_ms': NOW - 100}],
    }
    return expected, observed


def result(mut_e=None, mut_o=None):
    e, o = inputs()
    if mut_e:
        mut_e(e)
    if mut_o:
        mut_o(o)
    return evaluate_snapshot(e, o, NOW)


def test_clean_is_never_execution_or_authenticated():
    r = result()
    assert r['status'] == 'CONSISTENT_UNVERIFIED'
    assert not r['broker_authenticated']
    assert not r['protective_stop_broker_verified']
    assert not r['may_execute_real_order'] and not r['may_execute_paper_order']
    assert r['stress_loss_cash'] == '20'


@pytest.mark.parametrize('change,failed', [
    (lambda o: o.update(snapshot_id='prev'), 'snapshot_monotonic'),
    (lambda o: o.update(sequence=1), 'snapshot_monotonic'),
    (lambda o: o.update(observed_at_ms=NOW+1), 'snapshot_fresh'),
    (lambda o: o.update(observed_at_ms=NOW-4000), 'snapshot_fresh'),
    (lambda o: o.update(account_alias='wrong'), 'account_identity'),
    (lambda o: o.update(used_margin='1100'), 'margin_within_cap'),
    (lambda o: o.update(daily_realized_pnl='-100'), 'daily_realized_within_cap'),
    (lambda o: o['positions'][0].update(quantity='3'), 'positions_exactly_match'),
    (lambda o: o['positions'].append({'instrument':'EXTRA','side':'LONG','quantity':'1'}), 'positions_exactly_match'),
    (lambda o: o['quotes'][0].update(bid='94'), 'ABC:stop_not_breached'),
    (lambda o: o['quotes'][0].update(ask='99'), 'ABC:quote_order'),
    (lambda o: o['quotes'][0].update(ask='101'), 'ABC:spread'),
    (lambda o: o['quotes'][0].update(provider='Fake'), 'ABC:source_identity'),
    (lambda o: o['quotes'][0].update(observed_at_ms=NOW-4000), 'ABC:quote_fresh'),
    (lambda o: o['quotes'].clear(), 'quotes_exactly_match'),
    (lambda o: o.update(equity='90'), 'portfolio_gross_leverage'),
])
def test_observation_rejections(change, failed):
    r = result(mut_o=change)
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert failed in r['failed_checks']
    assert r['may_execute_real_order'] is False


def test_latched_circuit_blocks():
    assert 'circuit_not_latched' in result(mut_e=lambda e:e.update(circuit_latched=True))['failed_checks']


def test_daily_projected_downside_includes_stress_and_mark():
    r = result(mut_o=lambda o:o.update(daily_realized_pnl='-90'))
    assert 'projected_daily_downside' in r['failed_checks']


def test_position_stress_cap():
    assert 'ABC:position_loss_cap' in result(mut_e=lambda e:e.update(max_position_loss_cash='19'))['failed_checks']


def test_cfd_unsupported_and_short_cash_rejected():
    assert 'documented_account_api_scope' in result(mut_e=lambda e:e.update(broker='Trading212-CFD'),mut_o=lambda o:o.update(broker='Trading212-CFD'))['failed_checks']
    def short(e):
        e['positions'][0].update(side='SHORT',stop='105',stress_exit='110')
    r = result(mut_e=short, mut_o=lambda o:o['positions'][0].update(side='SHORT'))
    assert 'ABC:cash_account_long_only' in r['failed_checks']


def test_duplicate_quotes_rejected():
    e,o=inputs();o['quotes'].append(deepcopy(o['quotes'][0]))
    with pytest.raises(ValueError,match='Duplicate quote'):
        evaluate_snapshot(e,o,NOW)


@pytest.mark.parametrize('field,value', [('equity','NaN'),('equity','Infinity'),('equity','1e309'),('equity',1000.0),('equity','0'),('used_margin','-1')])
def test_invalid_money_fails_closed(field,value):
    e,o=inputs();o[field]=value
    with pytest.raises(ValueError):
        evaluate_snapshot(e,o,NOW)


def test_reject_unknown_fields_and_boolean_sequence():
    e,o=inputs();o['api_key']='secret'
    with pytest.raises(ValueError): evaluate_snapshot(e,o,NOW)
    e,o=inputs();o['sequence']=True
    with pytest.raises(ValueError): evaluate_snapshot(e,o,NOW)


def test_gap_beyond_stop_is_not_assumed_filled_at_stop():
    r=result(mut_o=lambda o:o['quotes'][0].update(bid='70',ask='70.1'))
    assert 'ABC:stop_not_breached' in r['failed_checks']
    assert r['marked_downside_cash']=='-60'
    assert r['may_execute_paper_order'] is False


def test_long_gap_beyond_declared_stress_uses_worse_bid_and_floors_notional():
    r = result(mut_o=lambda o: o['quotes'][0].update(bid='70', ask='70.1'))
    assert r['stress_loss_cash'] == '60'
    assert r['gross_notional_cash'] == '200'
    assert 'ABC:position_loss_cap' in r['failed_checks']
    assert 'ABC:stop_not_breached' in r['failed_checks']
    assert 'projected_daily_downside' in r['failed_checks']
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert not r['may_execute_paper_order'] and not r['may_execute_real_order']


def test_short_gap_beyond_declared_stress_uses_worse_ask():
    def short(e):
        e['positions'][0].update(side='SHORT', stop='105', stress_exit='110')
    def adverse_quote(o):
        o['positions'][0].update(side='SHORT')
        o['quotes'][0].update(bid='129.9', ask='130')
    r = result(mut_e=short, mut_o=adverse_quote)
    assert r['stress_loss_cash'] == '60'
    assert r['gross_notional_cash'] == '260'
    assert 'ABC:position_loss_cap' in r['failed_checks']
    assert 'ABC:stop_not_breached' in r['failed_checks']
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert r['may_execute_real_order'] is False


def test_stress_exit_still_bounds_loss_when_quote_has_not_gapped_past_it():
    r = result(mut_o=lambda o: o['quotes'][0].update(bid='94', ask='94.1'))
    assert r['stress_loss_cash'] == '20'
    assert r['gross_notional_cash'] == '200'
    assert 'ABC:stop_not_breached' in r['failed_checks']
    assert 'ABC:position_loss_cap' not in r['failed_checks']


def test_higher_ask_increases_gross_notional_without_trade_permission():
    r = result(mut_o=lambda o: o['quotes'][0].update(bid='109.9', ask='110'))
    assert r['gross_notional_cash'] == '220'
    assert r['stress_loss_cash'] == '20'
    assert r['status'] == 'CONSISTENT_UNVERIFIED'
    assert r['may_execute_real_order'] is False


def test_zero_positions_is_not_inferred_from_missing_broker_positions():
    r=result(mut_o=lambda o:o.update(positions=[]))
    assert 'positions_exactly_match' in r['failed_checks']


def test_snapshot_receipt_future_rejected():
    assert 'snapshot_fresh' in result(mut_o=lambda o:o.update(received_at_ms=NOW+1))['failed_checks']


def test_quote_received_after_snapshot_is_not_causal():
    # Quote is individually fresh, but it arrived AFTER the claimed snapshot.
    r = result(mut_o=lambda o: o['quotes'][0].update(received_at_ms=NOW-50))
    assert r['checks']['ABC:quote_fresh'] is True
    assert 'ABC:quote_snapshot_causal' in r['failed_checks']
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert r['may_execute_real_order'] is False


def test_replayed_quote_inside_age_limit_is_quarantined():
    # A new snapshot sequence cannot make a prior-snapshot quote fresh.
    def stale_from_prior(o):
        o['quotes'][0].update(observed_at_ms=NOW-3000, received_at_ms=NOW-2500)
    r = result(mut_o=stale_from_prior)
    assert r['checks']['ABC:quote_fresh'] is True
    assert 'ABC:quote_snapshot_causal' in r['failed_checks']
    assert r['status'] == 'HOLD_RECONCILIATION'


def test_clean_quote_causal_check_passes():
    r = result()
    assert r['checks']['ABC:quote_snapshot_causal'] is True
    assert r['status'] == 'CONSISTENT_UNVERIFIED'


def test_wrong_stop_side_rejected():
    e,o=inputs();e['positions'][0]['stop']='101'
    with pytest.raises(ValueError,match='Invalid long'):
        evaluate_snapshot(e,o,NOW)
