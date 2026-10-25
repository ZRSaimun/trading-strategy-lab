"""Offline synthetic tests: no broker credentials, quote feed or orders."""
from copy import deepcopy
import pytest
from app.live_order_review import build_review_packet, compare_review

NOW = 1_790_000_000_000


def intent(**changes):
    data = dict(broker='Trading212-Invest', account_alias='paper-account-1',
                instrument='TEST-EQUITY', venue='TEST', quote_provider='TEST',
                direction='BUY', client_order_id='unique-order-123', quote_id='q-12345678',
                currency='GBP', quantity='2', entry_price='100.02', stop_price='99',
                stressed_exit_price='98', point_value_cash='1', estimated_total_cost_cash='0.5',
                account_equity_cash='1000', existing_gross_notional_cash='100',
                existing_reserved_margin_cash='0', existing_reserved_risk_cash='1',
                daily_realized_pnl_cash='-1', daily_unrealized_pnl_cash='-2',
                max_position_loss_cash='10', max_daily_loss_cash='50',
                max_gross_leverage='1', margin_rate_percent='100',
                quote_bid='100', quote_ask='100.02', max_spread_bps='10',
                quote_observed_at_ms=NOW-200, quote_received_at_ms=NOW-100)
    data.update(changes)
    return data


def packet(**changes):
    return build_review_packet(intent(**changes), now_ms=NOW)


def test_hypothetical_valid_packet_never_authorizes_execution():
    p = packet()
    assert p['assumption_checks_pass'] and not p['failed_checks']
    assert p['may_execute_real_order'] is False and p['may_execute_paper_order'] is False
    assert not p['quote_authenticated'] and not p['owner_approval_recorded']
    assert compare_review(p, intent(), now_ms=NOW+100)['review_matches_exact_intent']
    assert not compare_review(p, intent(), now_ms=NOW+100)['may_execute_real_order']


@pytest.mark.parametrize('change,check', [
    ({'broker':'Trading212-CFD'}, 'official_api_account_supported'),
    ({'direction':'SELL','stop_price':'101','stressed_exit_price':'102','entry_price':'100'}, 'cash_account_buy_only'),
    ({'stop_price':'101'}, 'correct_stop_side'),
    ({'stressed_exit_price':'99.5'}, 'stressed_exit_worse_than_stop'),
    ({'entry_price':'99.99'}, 'entry_not_better_than_quote'),
    ({'quote_bid':'100.05'}, 'uncrossed_quote'),
    ({'quote_ask':'101'}, 'spread_within_cap'),
    ({'quote_observed_at_ms':NOW-5000}, 'quote_fresh'),
    ({'quote_received_at_ms':NOW+1}, 'quote_timestamp_order'),
    ({'quote_received_at_ms':NOW-100,'quote_observed_at_ms':NOW-2000}, 'transport_lag_ok'),
    ({'max_position_loss_cash':'1'}, 'per_position_loss_cap'),
    ({'max_position_loss_cash':'60'}, 'position_cap_within_daily_cap_and_equity'),
    ({'daily_realized_pnl_cash':'-49'}, 'projected_daily_loss_below_cap'),
    ({'existing_reserved_margin_cash':'900'}, 'portfolio_margin_within_equity'),
    ({'existing_gross_notional_cash':'900'}, 'portfolio_leverage_within_cap'),
    ({'existing_gross_notional_cash':'900','max_gross_leverage':'2'}, 'cash_account_fully_funded'),
])
def test_fail_closed_checks(change, check):
    p = packet(**change)
    assert check in p['failed_checks']
    assert not p['assumption_checks_pass']
    assert not p['may_execute_real_order']


@pytest.mark.parametrize('change', [
    {'quantity': '2.000000001'}, {'quantity': '1e3'}, {'quantity': 'NaN'},
    {'quantity': 2.0}, {'quantity': '-1'}, {'quantity': '0'},
    {'max_daily_loss_cash': '0'}, {'existing_reserved_risk_cash': '-1'},
    {'quote_observed_at_ms': True}, {'currency': 'GBP\n'},
    {'account_alias': 'bad alias'}, {'max_spread_bps': '10001'},
])
def test_invalid_input_rejected(change):
    with pytest.raises(ValueError):
        packet(**change)


def test_extra_field_rejected():
    with pytest.raises(ValueError):
        packet(secret='not-allowed')


def test_digest_binds_order_quote_identity_and_review_time():
    p = packet()
    for field, value in [('client_order_id','unique-order-999'), ('quote_id','q-99999999'),
                         ('quote_provider','OTHER'), ('account_alias','other-account'),
                         ('quantity','3'), ('quote_ask','100.03'), ('max_daily_loss_cash','60')]:
        revised = intent(**{field:value})
        r = compare_review(p, revised, now_ms=NOW+1)
        assert not r['review_matches_exact_intent'] and r['requires_new_human_review']
    assert p['review_sha256'] != build_review_packet(intent(), now_ms=NOW+1)['review_sha256']


def test_canonical_decimal_equivalence_and_expiry():
    p = packet()
    assert compare_review(p, intent(quantity='2.0'), now_ms=NOW+29999)['review_matches_exact_intent']
    assert compare_review(p, intent(), now_ms=NOW+1000)['quote_still_fresh']
    assert compare_review(p, intent(), now_ms=NOW+4000)['requires_new_human_review']
    assert not compare_review(p, intent(), now_ms=NOW+4000)['quote_still_fresh']
    assert not compare_review(p, intent(), now_ms=NOW+30000)['review_not_expired']
    assert compare_review(p, intent(), now_ms=NOW-1)['requires_new_human_review']


def test_review_policy_change_invalidates_digest():
    p = packet()
    assert not compare_review(p, intent(), now_ms=NOW+1, max_quote_age_ms=5000)['review_matches_exact_intent']


def test_invalid_clock_and_fingerprint_rejected():
    with pytest.raises(ValueError):
        build_review_packet(intent(), now_ms=True)
    with pytest.raises(ValueError):
        build_review_packet(intent(), now_ms=NOW, ttl_ms=100000)
    with pytest.raises(ValueError):
        compare_review({'review_sha256':'notahash'}, intent(), now_ms=NOW)
    with pytest.raises(ValueError):
        compare_review({'review_sha256':'0'*64,'issued_at_ms':NOW,'expires_at_ms':NOW+100000}, intent(), now_ms=NOW)


def test_stressed_gap_not_optimistically_priced_at_stop():
    p = packet()
    assert p['stressed_loss_cash'] == '4.54'  # (100.02 - 98) * 2 + 0.5
    assert p['projected_daily_pnl_cash'] == '-8.54'


def test_unrealized_gains_do_not_expand_daily_loss_budget():
    a = packet(daily_unrealized_pnl_cash='1000')
    b = packet(daily_unrealized_pnl_cash='0')
    assert a['projected_daily_pnl_cash'] == b['projected_daily_pnl_cash']


def test_pure_repeatability():
    x = intent()
    original = deepcopy(x)
    assert build_review_packet(x, now_ms=NOW) == build_review_packet(x, now_ms=NOW)
    assert x == original


@pytest.mark.parametrize('bid,ask', [
    ('99', '99.02'),       # Exact BUY stop touch
    ('98.5', '98.52'),     # Already through the BUY stop
])
def test_current_executable_bid_breaches_buy_stop(bid, ask):
    p = packet(quote_bid=bid, quote_ask=ask)
    assert 'protective_stop_not_breached' in p['failed_checks']
    assert not p['assumption_checks_pass']
    assert not p['may_execute_paper_order'] and not p['may_execute_real_order']


def test_buy_gap_worse_than_stress_exit_is_charged_at_bid():
    p = packet(quote_bid='90', quote_ask='90.02')
    assert p['stressed_loss_cash'] == '20.54'
    assert 'per_position_loss_cap' in p['failed_checks']
    assert 'protective_stop_not_breached' in p['failed_checks']
    assert p['projected_daily_pnl_cash'] == '-24.54'


def test_sell_gap_worse_than_stress_exit_is_charged_at_ask():
    p = packet(direction='SELL', entry_price='100', stop_price='101',
               stressed_exit_price='102', quote_bid='105', quote_ask='105.02')
    assert p['stressed_loss_cash'] == '10.54'
    assert 'protective_stop_not_breached' in p['failed_checks']
    assert 'per_position_loss_cap' in p['failed_checks']
    assert not p['may_execute_real_order']


def test_stressed_margin_can_fail_even_when_current_margin_passes():
    p = packet(existing_reserved_margin_cash='799')
    assert p['checks']['portfolio_margin_within_equity']
    assert not p['checks']['stressed_portfolio_margin_within_equity']
    assert not p['may_execute_paper_order']


def test_stressed_leverage_can_fail_even_when_current_leverage_passes():
    p = packet(existing_gross_notional_cash='799')
    assert p['checks']['portfolio_leverage_within_cap']
    assert not p['checks']['stressed_portfolio_leverage_within_cap']
    assert not p['may_execute_real_order']
