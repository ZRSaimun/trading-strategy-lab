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



@pytest.mark.parametrize('field,forged', [
    ('assumption_checks_pass', False),
    ('failed_checks', ['quote_fresh']),
    ('stressed_loss_cash', '0'),
    ('quote_authenticated', True),
    ('may_execute_real_order', True),
    ('may_execute_paper_order', True),
    ('warnings', []),
    ('checks', {'quote_fresh': False}),
    ('schema', 'live-order-review-v2'),
])
def test_modified_review_output_requires_fresh_human_review(field, forged):
    original = packet()
    altered = deepcopy(original)
    altered[field] = forged
    assert altered['review_sha256'] == original['review_sha256']
    assert compare_review(original, intent(), now_ms=NOW+1)['review_matches_exact_intent']
    result = compare_review(altered, intent(), now_ms=NOW+1)
    assert result['review_matches_exact_intent'] is False
    assert result['requires_new_human_review'] is True
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False


def test_missing_or_extra_review_field_requires_fresh_human_review():
    original = packet()
    missing = deepcopy(original)
    del missing['quote_authenticated']
    extra = deepcopy(original)
    extra['owner_note'] = 'not part of the reviewed packet'
    for altered in (missing, extra):
        result = compare_review(altered, intent(), now_ms=NOW+1)
        assert not result['review_matches_exact_intent']
        assert result['requires_new_human_review']
    assert compare_review(original, intent(), now_ms=NOW+1)['review_matches_exact_intent']


def test_equivalent_decimal_formatting_preserves_full_packet_consistency():
    # Same economic intent may render computed cash amounts with trailing zeros.
    original = build_review_packet(intent(quantity='2.0'), now_ms=NOW)
    assert compare_review(original, intent(quantity='2'), now_ms=NOW+1)['review_matches_exact_intent']
    assert compare_review(packet(), intent(quantity='2.0'), now_ms=NOW+1)['review_matches_exact_intent']
    modified = deepcopy(original)
    modified['stressed_loss_cash'] = '0'
    assert compare_review(modified, intent(quantity='2'), now_ms=NOW+1)['requires_new_human_review']


def test_nested_flag_type_substitution_does_not_match_review():
    altered = packet()
    altered['checks']['quote_fresh'] = 1  # 1 == True in Python, but not JSON.
    assert not compare_review(altered, intent(), now_ms=NOW+1)['review_matches_exact_intent']
    assert compare_review(altered, intent(), now_ms=NOW+1)['requires_new_human_review']


@pytest.mark.parametrize('field', ['warnings', 'failed_checks'])
def test_json_equivalent_tuple_does_not_match_typed_review_packet(field):
    # json.dumps(tuple) and json.dumps(list) are identical, but a review
    # packet is a typed JSON-compatible object, not an arbitrary Python value.
    original = packet()
    altered = deepcopy(original)
    altered[field] = tuple(altered[field])
    result = compare_review(altered, intent(), now_ms=NOW+1)
    assert not result['review_matches_exact_intent']
    assert result['requires_new_human_review']
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False
    assert compare_review(original, intent(), now_ms=NOW+1)['review_matches_exact_intent']


def test_deeply_nested_untrusted_check_fails_closed_without_recursion():
    # The old JSON round-trip comparison could raise RecursionError instead
    # of returning a conservative re-review decision for a malformed packet.
    altered = packet()
    nested = []
    for _ in range(1200):
        nested = [nested]
    altered['checks']['quote_fresh'] = nested
    result = compare_review(altered, intent(), now_ms=NOW+1)
    assert not result['review_matches_exact_intent']
    assert result['requires_new_human_review']
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False


def test_typed_review_packet_preserves_decimal_equivalence_and_flag_checks():
    original = packet(quantity='2.0')
    assert compare_review(original, intent(quantity='2'), now_ms=NOW+1)['review_matches_exact_intent']
    altered = deepcopy(original)
    altered['checks']['quote_fresh'] = 1
    assert compare_review(altered, intent(quantity='2'), now_ms=NOW+1)['requires_new_human_review']


def test_review_policy_change_invalidates_digest():
    p = packet()
    assert not compare_review(p, intent(), now_ms=NOW+1, max_quote_age_ms=2500)['review_matches_exact_intent']


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


def test_realized_gains_cannot_replenish_daily_risk_budget():
    # Reserved risk plus new stressed loss exceeds the declared 50 cash cap.
    # A windfall recorded earlier in the day must not make this pass.
    kwargs = dict(existing_reserved_risk_cash='47', daily_unrealized_pnl_cash='0')
    baseline = packet(daily_realized_pnl_cash='0', **kwargs)
    windfall = packet(daily_realized_pnl_cash='1000', **kwargs)
    assert baseline['projected_daily_pnl_cash'] == '-51.54'
    assert windfall['projected_daily_pnl_cash'] == baseline['projected_daily_pnl_cash']
    assert 'projected_daily_loss_below_cap' in windfall['failed_checks']
    assert not windfall['assumption_checks_pass']
    assert compare_review(windfall, intent(daily_realized_pnl_cash='1000', **kwargs),
                          now_ms=NOW+1)['requires_new_human_review']
    assert windfall['may_execute_real_order'] is False
    assert windfall['may_execute_paper_order'] is False


def test_realized_losses_still_reduce_daily_risk_capacity():
    kwargs = dict(existing_reserved_risk_cash='47', daily_unrealized_pnl_cash='0')
    no_realized_loss = packet(daily_realized_pnl_cash='0', **kwargs)
    realized_loss = packet(daily_realized_pnl_cash='-10', **kwargs)
    assert no_realized_loss['projected_daily_pnl_cash'] == '-51.54'
    assert realized_loss['projected_daily_pnl_cash'] == '-61.54'
    assert 'projected_daily_loss_below_cap' in realized_loss['failed_checks']


def test_pure_repeatability():
    x = intent()
    original = deepcopy(x)
    assert build_review_packet(x, now_ms=NOW) == build_review_packet(x, now_ms=NOW)
    assert x == original


@pytest.mark.parametrize('change,check', [
    ({'max_position_loss_cash': '51'}, 'declared_position_budget_at_most_5pct_equity'),
    ({'max_daily_loss_cash': '101'}, 'declared_daily_budget_at_most_10pct_equity'),
    ({'max_gross_leverage': '5.00000001'}, 'declared_leverage_policy_at_most_5x'),
    ({'max_spread_bps': '100.00000001'}, 'declared_spread_policy_at_most_100bps'),
])
def test_untrusted_risk_policy_cannot_relax_conservative_review_ceiling(change, check):
    result = packet(**change)
    assert check in result['failed_checks']
    assert result['assumption_checks_pass'] is False
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False


@pytest.mark.parametrize('policy', [
    {'max_quote_age_ms': 3001},
    {'max_transport_lag_ms': 1001},
    {'max_quote_age_ms': 60000},
    {'max_transport_lag_ms': 60000},
])
def test_quote_timing_policy_cannot_be_relaxed(policy):
    with pytest.raises(ValueError, match='Invalid timing policy'):
        build_review_packet(intent(), now_ms=NOW, **policy)
    with pytest.raises(ValueError, match='Invalid timing policy'):
        compare_review(packet(), intent(), now_ms=NOW+1, **policy)


def test_conservative_ceilings_accept_boundary_values_but_never_execute():
    result = packet(max_position_loss_cash='50', max_daily_loss_cash='100',
                    max_gross_leverage='5', max_spread_bps='100')
    for check in ('declared_position_budget_at_most_5pct_equity',
                  'declared_daily_budget_at_most_10pct_equity',
                  'declared_leverage_policy_at_most_5x',
                  'declared_spread_policy_at_most_100bps'):
        assert result['checks'][check] is True
    assert result['assumption_checks_pass'] is True
    assert result['may_execute_real_order'] is False
    assert result['may_execute_paper_order'] is False


def test_new_policy_checks_preserve_existing_position_loss_calculation():
    baseline = packet()
    assert baseline['stressed_loss_cash'] == '4.54'
    assert baseline['checks']['declared_position_budget_at_most_5pct_equity']
    assert baseline['checks']['declared_daily_budget_at_most_10pct_equity']
    assert baseline['checks']['declared_leverage_policy_at_most_5x']
    assert baseline['checks']['declared_spread_policy_at_most_100bps']


# Regression cases carried forward from PR #79; preserve both safety layers.
@pytest.mark.parametrize('bid,ask', [
    ('99', '99.02'),
    ('98.5', '98.52'),
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


def test_conservative_ceilings_and_stop_breach_are_both_enforced():
    p = packet(quote_bid='90', quote_ask='90.02', max_position_loss_cash='51',
               max_daily_loss_cash='101', max_gross_leverage='5.00000001',
               max_spread_bps='100.00000001')
    for check in ('protective_stop_not_breached',
                  'declared_position_budget_at_most_5pct_equity',
                  'declared_daily_budget_at_most_10pct_equity',
                  'declared_leverage_policy_at_most_5x',
                  'declared_spread_policy_at_most_100bps'):
        assert check in p['failed_checks']
    assert p['may_execute_real_order'] is False


@pytest.mark.parametrize('broker', ['Trading212-Invest', 'Trading212-StocksISA'])
def test_cash_account_funding_includes_declared_costs(broker):
    # The purchase itself fits, but the declared round-trip costs do not.
    order = intent(broker=broker, existing_gross_notional_cash='799.56',
                   max_gross_leverage='2')
    result = build_review_packet(order, now_ms=NOW)
    assert result['combined_notional_cash'] == '999.60'
    assert result['checks']['portfolio_leverage_within_cap']
    assert result['checks']['stressed_portfolio_leverage_within_cap']
    assert result['failed_checks'] == ['cash_account_fully_funded']
    assert not result['assumption_checks_pass']
    assert compare_review(result, order, now_ms=NOW+1)['requires_new_human_review']
    assert result['may_execute_paper_order'] is False
    assert result['may_execute_real_order'] is False


@pytest.mark.parametrize('gross,cost,expected', [
    ('799.46', '0.5', True),   # 999.50 + 0.50 = exactly 1,000
    ('799.47', '0.5', False),  # 999.51 + 0.50 = 1,000.01
    ('799.56', '0', True),     # zero declared costs need no extra buffer
])
def test_cash_account_funding_fee_boundary_is_exact_decimal(gross, cost, expected):
    result = packet(existing_gross_notional_cash=gross,
                    estimated_total_cost_cash=cost, max_gross_leverage='2')
    assert result['checks']['cash_account_fully_funded'] is expected
    assert ('cash_account_fully_funded' in result['failed_checks']) is not expected
    assert result['may_execute_real_order'] is False
