"""Synthetic FX risk scenarios, never broker market data or execution tests."""
from copy import deepcopy
import pytest
from app.paper_fx_liability_guard import evaluate_paper_fx_liabilities

NOW = 1_800_000_000_000


def sample():
    return dict(
        account_currency='GBP', equity_cash='10000',
        daily_realized_pnl_cash='-100', daily_unrealized_pnl_cash='-50',
        max_daily_loss_cash='1500', max_total_stressed_loss_cash='2000',
        max_single_stressed_loss_cash='1500', max_gross_leverage='3',
        max_margin_fraction='0.8', emergency_latched=False,
        max_fx_quote_age_ms=3000, max_transport_lag_ms=1000,
        max_spread_bps='150', fx_shock_bps='100',
        exposures=[dict(client_order_id='order-1', instrument='XAUUSD',
                        settlement_currency='USD', state='OPEN',
                        stressed_loss_settlement='100',
                        gross_notional_settlement='1000',
                        reserved_margin_settlement='100')],
        fx_quotes=[dict(base_currency='USD', quote_currency='GBP',
                        provider='synthetic', venue='fixture', quote_id='fx-1',
                        sequence=2, previous_sequence=1, previous_quote_id='fx-0',
                        bid='0.79', ask='0.80',
                        observed_at_ms=NOW-500, received_at_ms=NOW-200)],
    )


def run(s=None):
    return evaluate_paper_fx_liabilities(s if s is not None else sample(), now_ms=NOW)


def test_ask_plus_shock_converts_all_liabilities():
    r = run()
    assert r['status'] == 'REVIEW_ONLY_UNVERIFIED'
    assert r['total_stressed_loss_cash'] == '80.8000'
    assert r['total_gross_notional_cash'] == '808.0000'
    assert r['total_reserved_margin_cash'] == '80.8000'
    assert r['stressed_equity_cash'] == '9919.2000'
    assert not r['may_execute_real_order'] and not r['may_execute_paper_order']
    assert not r['fx_source_authenticated'] and not r['durable_risk_reservation']


def test_uses_ask_not_mid_or_bid():
    s = sample()
    s['fx_quotes'][0]['bid'] = '0.70'
    s['max_spread_bps'] = '2000'
    assert run(s)['total_stressed_loss_cash'] == '80.8000'


def test_account_currency_requires_no_fx_quote():
    s = sample()
    s['exposures'][0]['settlement_currency'] = 'GBP'
    s['fx_quotes'] = []
    r = run(s)
    assert r['status'] == 'REVIEW_ONLY_UNVERIFIED'
    assert r['total_stressed_loss_cash'] == '100'


def test_aggregate_mixed_currency_exposures():
    s = sample()
    s['exposures'].append(dict(client_order_id='order-2', instrument='FTSE',
                               settlement_currency='GBP', state='PENDING',
                               stressed_loss_settlement='20',
                               gross_notional_settlement='300',
                               reserved_margin_settlement='50'))
    r = run(s)
    assert r['total_stressed_loss_cash'] == '100.8000'
    assert r['total_gross_notional_cash'] == '1108.0000'


def test_missing_fx_pair_holds_without_reporting_partial_exposure():
    s = sample()
    s['fx_quotes'] = []
    r = run(s)
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert 'exact_fx_coverage' in r['failed_checks']
    assert r['total_stressed_loss_cash'] is None


def test_unused_fx_quote_is_rejected_as_coverage_failure():
    s = sample()
    s['exposures'][0]['settlement_currency'] = 'GBP'
    assert run(s)['status'] == 'HOLD_RECONCILIATION'


@pytest.mark.parametrize('change,failed', [
    (lambda s: s['fx_quotes'][0].update(observed_at_ms=NOW-3001), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(received_at_ms=NOW+1), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(received_at_ms=NOW-4000), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(observed_at_ms=NOW-2000, received_at_ms=NOW), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(bid='0.81'), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(bid='0.70'), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(sequence=1), 'all_fx_quotes_safe'),
    (lambda s: s['fx_quotes'][0].update(quote_id='fx-0'), 'all_fx_quotes_safe'),
    (lambda s: s.update(emergency_latched=True), 'emergency_circuit_clear'),
    (lambda s: s['exposures'][0].update(state='UNKNOWN'), 'all_order_outcomes_known'),
    (lambda s: s['exposures'][0].update(state='CANCEL_PENDING'), 'all_order_outcomes_known'),
    (lambda s: s.update(max_single_stressed_loss_cash='50'), 'single_loss_within_limit'),
    (lambda s: s.update(max_total_stressed_loss_cash='70', max_single_stressed_loss_cash='70'), 'aggregate_loss_within_limit'),
    (lambda s: s.update(daily_realized_pnl_cash='-1490'), 'daily_loss_within_limit'),
    (lambda s: s.update(max_gross_leverage='0.05'), 'stressed_gross_leverage_within_limit'),
    (lambda s: s.update(max_margin_fraction='0.001'), 'stressed_margin_within_limit'),
])
def test_unsafe_scenarios_fail_closed(change, failed):
    s = sample()
    change(s)
    r = run(s)
    assert r['status'] == 'HOLD_RECONCILIATION'
    assert failed in r['failed_checks']
    assert not r['may_execute_real_order']


@pytest.mark.parametrize('change', [
    lambda s: s['fx_quotes'][0].update(quote_currency='EUR'),
    lambda s: s['fx_quotes'][0].update(base_currency='GBP'),
    lambda s: s['fx_quotes'].append(deepcopy(s['fx_quotes'][0])),
    lambda s: s['exposures'].append(deepcopy(s['exposures'][0])),
    lambda s: s['exposures'][0].update(state='FILLED'),
    lambda s: s['exposures'][0].update(stressed_loss_settlement='-1'),
    lambda s: s['exposures'][0].update(stressed_loss_settlement='NaN'),
    lambda s: s['exposures'][0].update(stressed_loss_settlement='1e4'),
    lambda s: s['exposures'][0].update(settlement_currency='usd'),
    lambda s: s['fx_quotes'][0].update(bid='0'),
    lambda s: s['fx_quotes'][0].update(sequence=True),
    lambda s: s['fx_quotes'][0].update(provider=''),
    lambda s: s['fx_quotes'][0].update(secret='unsafe'),
    lambda s: s.update(api_key='unsafe'),
    lambda s: s.update(fx_shock_bps='-1'),
    lambda s: s.update(fx_shock_bps='5001'),
    lambda s: s.update(max_margin_fraction='1.01'),
    lambda s: s.update(max_total_stressed_loss_cash='11000'),
    lambda s: s.update(max_single_stressed_loss_cash='3000'),
    lambda s: s.update(max_daily_loss_cash='11000'),
    lambda s: s.update(emergency_latched=1),
    lambda s: s.update(exposures='not-list'),
    lambda s: s.update(fx_quotes=[s['fx_quotes'][0]] * 33),
])
def test_invalid_inputs_raise(change):
    s = sample()
    change(s)
    with pytest.raises(ValueError):
        run(s)


def test_nonpositive_stressed_equity_blocks_even_if_other_caps_relaxed():
    s = sample()
    s['equity_cash'] = '100'
    s['max_total_stressed_loss_cash'] = '100'
    s['max_single_stressed_loss_cash'] = '100'
    s['max_daily_loss_cash'] = '100'
    s['exposures'][0]['stressed_loss_settlement'] = '125'
    r = run(s)
    assert r['stressed_equity_cash'] == '-1.0000'
    assert 'stressed_equity_positive' in r['failed_checks']


def test_no_exposure_is_non_executing_and_no_quote_needed():
    s = sample()
    s['exposures'] = []
    s['fx_quotes'] = []
    r = run(s)
    assert r['status'] == 'REVIEW_ONLY_UNVERIFIED'
    assert r['total_stressed_loss_cash'] == '0'
    assert r['may_execute_paper_order'] is False


def test_no_mutation_and_deterministic_diagnostic():
    s = sample()
    before = deepcopy(s)
    a, b = run(s), run(s)
    assert a == b and s == before
    s['fx_quotes'][0]['ask'] = '0.81'
    assert run(s)['diagnostic_sha256'] != a['diagnostic_sha256']


def test_bool_server_clock_rejected():
    with pytest.raises(ValueError):
        evaluate_paper_fx_liabilities(sample(), now_ms=True)
