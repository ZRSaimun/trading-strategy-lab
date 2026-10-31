"""Synthetic signed-decision checks. No real owner keys, broker or orders."""
from copy import deepcopy
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from app.paper_signed_order_decision_fence import (
    evaluate_signed_order_decision, signing_message,
)

NOW = 1_790_000_000_000
KEY = Ed25519PrivateKey.generate()
PUB = KEY.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()


def expected(**updates):
    result = dict(owner_key_id='owner-key-v1', account_alias='paper-acc-01',
                  client_order_id='order-unique-001', quote_id='quote-unique-01',
                  review_sha256='a'*64, risk_policy_sha256='b'*64,
                  inventory_sha256='c'*64, review_issued_at_ms=NOW-700,
                  review_expires_at_ms=NOW+20000, quote_observed_at_ms=NOW-1000,
                  quote_received_at_ms=NOW-800)
    result.update(updates)
    return result


def decision(**updates):
    e = expected()
    p = dict(schema='paper-signed-order-decision-v1', action='APPROVE',
             owner_key_id=e['owner_key_id'], account_alias=e['account_alias'],
             client_order_id=e['client_order_id'], quote_id=e['quote_id'],
             review_sha256=e['review_sha256'], risk_policy_sha256=e['risk_policy_sha256'],
             inventory_sha256=e['inventory_sha256'], nonce='1'*32,
             signed_at_ms=NOW-300, expires_at_ms=NOW+2000,
             signature_hex='0'*128)
    p.update(updates)
    p['signature_hex'] = KEY.sign(signing_message(p)).hex()
    return p


def run(d=None, e=None, **kwargs):
    return evaluate_signed_order_decision(
        d if d is not None else decision(),
        expected=e if e is not None else expected(),
        trusted_public_key_hex=kwargs.pop('trusted_public_key_hex', PUB),
        now_ms=kwargs.pop('now_ms', NOW),
        used_nonces=kwargs.pop('used_nonces', []),
        kill_switch_active=kwargs.pop('kill_switch_active', False),
        reconciliation_healthy=kwargs.pop('reconciliation_healthy', True),
        **kwargs,
    )


def test_valid_signature_is_still_non_executable():
    out = run()
    assert out['declared_evidence_checks_pass']
    assert out['status'] == 'HOLD_RECONCILIATION'
    assert out['signature_valid']
    assert out['owner_identity_authenticated'] is False
    assert out['nonce_durably_reserved_or_consumed'] is False
    assert out['may_execute_real_order'] is False
    assert out['may_execute_paper_order'] is False


@pytest.mark.parametrize('field,value', [
    ('owner_key_id', 'other-key'), ('account_alias', 'other-account'),
    ('client_order_id', 'order-unique-999'), ('quote_id', 'quote-unique-99'),
    ('review_sha256', 'd'*64), ('risk_policy_sha256', 'd'*64),
    ('inventory_sha256', 'd'*64),
])
def test_re_signed_but_wrong_binding_still_holds(field, value):
    out = run(d=decision(**{field: value}))
    assert out['signature_valid']
    assert 'exact_order_review_and_inventory_binding' in out['failed_checks']
    assert not out['may_execute_real_order']


def test_modified_payload_invalidates_signature():
    d = decision()
    d['client_order_id'] = 'order-unique-999'
    assert not run(d=d)['signature_valid']


def test_modified_signature_rejected():
    d = decision()
    d['signature_hex'] = 'f'*128
    assert 'signature_valid_for_pinned_key' in run(d=d)['failed_checks']


def test_other_pinned_key_rejected():
    other = Ed25519PrivateKey.generate().public_key().public_bytes(Encoding.Raw, PublicFormat.Raw).hex()
    assert not run(trusted_public_key_hex=other)['signature_valid']


@pytest.mark.parametrize('change,failed', [
    ({'action':'REJECT'}, 'specific_approval_not_rejection'),
    ({'signed_at_ms':NOW+1}, 'review_clock_consistent'),
    ({'signed_at_ms':NOW-1000}, 'review_clock_consistent'),
    ({'expires_at_ms':NOW}, 'decision_not_expired'),
    ({'expires_at_ms':NOW+30001}, 'decision_not_expired'),
    ({'expires_at_ms':NOW-100}, 'decision_not_expired'),
])
def test_decision_state_and_time(change, failed):
    assert failed in run(d=decision(**change))['failed_checks']


@pytest.mark.parametrize('change,failed', [
    ({'quote_observed_at_ms':NOW-3001}, 'quote_fresh_at_decision_and_now'),
    ({'quote_received_at_ms':NOW+1}, 'quote_observed_and_delivered_before_decision'),
    ({'quote_received_at_ms':NOW-100,'quote_observed_at_ms':NOW-1500}, 'quote_transport_within_limit'),
    ({'review_expires_at_ms':NOW+1}, 'decision_not_expired'),
])
def test_expected_quote_and_review_time_fail_closed(change, failed):
    assert failed in run(e=expected(**change))['failed_checks']


def test_replay_breaker_and_reconciliation():
    assert 'nonce_not_in_declared_used_snapshot' in run(used_nonces=['1'*32])['failed_checks']
    assert 'kill_switch_inactive' in run(kill_switch_active=True)['failed_checks']
    assert 'reconciliation_declared_healthy' in run(reconciliation_healthy=False)['failed_checks']


@pytest.mark.parametrize('field,value', [
    ('nonce', 'x'*32), ('review_sha256', 'A'*64), ('signature_hex', '0'),
    ('action', 'CANCEL'), ('signed_at_ms', True), ('expires_at_ms', -1),
    ('client_order_id', 'bad id'), ('schema', 'unexpected'),
])
def test_malformed_decision_rejected(field, value):
    d = decision()
    d[field] = value
    with pytest.raises(ValueError):
        run(d=d)


@pytest.mark.parametrize('bad', [
    None, [], 'invalid', True, 10, 'A'*64,
])
def test_bad_trust_anchor_rejected(bad):
    with pytest.raises(ValueError):
        run(trusted_public_key_hex=bad)


@pytest.mark.parametrize('bad', [None, {}, ['bad'], ['1'*32]*2, ['1'*32]*1025])
def test_bad_used_nonce_snapshots_rejected(bad):
    with pytest.raises(ValueError):
        run(used_nonces=bad)


def test_unexpected_fields_rejected():
    d = decision()
    d['may_execute_real_order'] = True
    with pytest.raises(ValueError):
        run(d=d)
    e = expected()
    e['owner_authenticated'] = True
    with pytest.raises(ValueError):
        run(e=e)


def test_purity_deterministic_audit_and_no_private_key_in_output():
    d, e = decision(), expected()
    before_d, before_e = deepcopy(d), deepcopy(e)
    first = run(d=d, e=e)
    assert first == run(d=d, e=e)
    assert d == before_d and e == before_e
    assert 'signature_hex' not in first and 'private_key' not in repr(first)
    assert len(first['audit_sha256']) == 64


def test_expired_quote_even_if_decision_still_valid():
    out = run(now_ms=NOW+2500)
    assert 'quote_fresh_at_decision_and_now' in out['failed_checks']
    assert 'decision_not_expired' in out['failed_checks']
    assert not out['declared_evidence_checks_pass']


def test_quote_at_exact_age_boundary_passes_only_if_others_valid():
    out = run(now_ms=NOW+2000)
    assert out['checks']['quote_fresh_at_decision_and_now']
    assert 'decision_not_expired' in out['failed_checks']
