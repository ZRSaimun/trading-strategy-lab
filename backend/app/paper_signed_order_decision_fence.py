"""Offline Ed25519 order-decision evidence preflight; never an execution grant.

The trusted expected snapshot and public key MUST come from an independent,
server-pinned source in any future integration. This module does not authenticate
broker data, persist a nonce, record human presence or place any order.
"""

import hashlib
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

MAX_TIME = 8_640_000_000_000_000
MAX_QUOTE_AGE_MS = 3000
MAX_TRANSPORT_MS = 1000
MAX_DECISION_TTL_MS = 30000
SCHEMA = 'paper-signed-order-decision-v1'

PAYLOAD_FIELDS = frozenset({
    'schema', 'action', 'owner_key_id', 'account_alias', 'client_order_id',
    'quote_id', 'review_sha256', 'risk_policy_sha256', 'inventory_sha256',
    'nonce', 'signed_at_ms', 'expires_at_ms',
})
EXPECTED_FIELDS = frozenset({
    'owner_key_id', 'account_alias', 'client_order_id', 'quote_id',
    'review_sha256', 'risk_policy_sha256', 'inventory_sha256',
    'review_issued_at_ms', 'review_expires_at_ms',
    'quote_observed_at_ms', 'quote_received_at_ms',
})
IDENTITY_FIELDS = ('owner_key_id', 'account_alias', 'client_order_id', 'quote_id')
DIGEST_FIELDS = ('review_sha256', 'risk_policy_sha256', 'inventory_sha256')
ID_PATTERN = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z')
HEX64 = re.compile(r'[0-9a-f]{64}\Z')
HEX32 = re.compile(r'[0-9a-f]{32}\Z')
HEX128 = re.compile(r'[0-9a-f]{128}\Z')


def _timestamp(value, name):
    if type(value) is not int or not 0 <= value <= MAX_TIME:
        raise ValueError(f'{name}: invalid UTC epoch milliseconds')
    return value


def _identifier(value, name):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise ValueError(f'{name}: invalid identifier')
    return value


def _digest(value, name):
    if not isinstance(value, str) or not HEX64.fullmatch(value):
        raise ValueError(f'{name}: expected lowercase SHA-256 hex')
    return value


def _payload(decision):
    if not isinstance(decision, dict) or set(decision) != PAYLOAD_FIELDS | {'signature_hex'}:
        raise ValueError('Decision must contain exactly the required fields')
    payload = {name: _identifier(decision[name], name) for name in IDENTITY_FIELDS}
    payload.update({name: _digest(decision[name], name) for name in DIGEST_FIELDS})
    if decision['schema'] != SCHEMA or decision['action'] not in ('APPROVE', 'REJECT'):
        raise ValueError('Invalid decision schema or action')
    payload['schema'] = SCHEMA
    payload['action'] = decision['action']
    nonce = decision['nonce']
    if not isinstance(nonce, str) or not HEX32.fullmatch(nonce):
        raise ValueError('nonce: expected 128-bit lowercase hex')
    payload['nonce'] = nonce
    for name in ('signed_at_ms', 'expires_at_ms'):
        payload[name] = _timestamp(decision[name], name)
    signature = decision['signature_hex']
    if not isinstance(signature, str) or not HEX128.fullmatch(signature):
        raise ValueError('signature_hex: expected 64-byte lowercase hex')
    return payload


def signing_message(decision):
    """Canonical message bytes for external Ed25519 signers; never signs data."""
    payload = _payload(decision)
    return json.dumps(payload, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True).encode('ascii')


def _expected(snapshot):
    if not isinstance(snapshot, dict) or set(snapshot) != EXPECTED_FIELDS:
        raise ValueError('Expected snapshot must contain exactly the required fields')
    result = {name: _identifier(snapshot[name], name) for name in IDENTITY_FIELDS}
    result.update({name: _digest(snapshot[name], name) for name in DIGEST_FIELDS})
    for name in ('review_issued_at_ms', 'review_expires_at_ms',
                 'quote_observed_at_ms', 'quote_received_at_ms'):
        result[name] = _timestamp(snapshot[name], name)
    return result


def evaluate_signed_order_decision(decision, *, expected, trusted_public_key_hex,
                                   now_ms, used_nonces, kill_switch_active,
                                   reconciliation_healthy):
    """Validate one declared decision, ALWAYS returning HOLD_RECONCILIATION.

    `expected`, public key, server time, used nonces and breaker state must be
    independently sourced and durable in a future adapter. No side effects.
    """
    now_ms = _timestamp(now_ms, 'now_ms')
    if type(kill_switch_active) is not bool or type(reconciliation_healthy) is not bool:
        raise ValueError('Risk gate flags must be booleans')
    if not isinstance(trusted_public_key_hex, str) or not HEX64.fullmatch(trusted_public_key_hex):
        raise ValueError('Trusted Ed25519 public key must be 32-byte lowercase hex')
    if not isinstance(used_nonces, (list, tuple)) or len(used_nonces) > 1024:
        raise ValueError('Bounded durable used-nonce snapshot required')
    if any(not isinstance(n, str) or not HEX32.fullmatch(n) for n in used_nonces):
        raise ValueError('Invalid used-nonce entry')
    if len(set(used_nonces)) != len(used_nonces):
        raise ValueError('Duplicate used-nonce snapshot entry')
    e = _expected(expected)
    p = _payload(decision)
    message = signing_message(decision)
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(trusted_public_key_hex)).verify(
            bytes.fromhex(decision['signature_hex']), message)
        signature_valid = True
    except (InvalidSignature, ValueError):
        signature_valid = False

    checks = {}
    checks['signature_valid_for_pinned_key'] = signature_valid
    checks['exact_order_review_and_inventory_binding'] = all(
        p[name] == e[name] for name in (*IDENTITY_FIELDS, *DIGEST_FIELDS))
    checks['specific_approval_not_rejection'] = p['action'] == 'APPROVE'
    checks['review_clock_consistent'] = (
        e['review_issued_at_ms'] <= p['signed_at_ms'] <= now_ms
        and e['review_issued_at_ms'] < e['review_expires_at_ms'])
    checks['decision_not_expired'] = (
        p['signed_at_ms'] < p['expires_at_ms']
        and p['expires_at_ms'] - p['signed_at_ms'] <= MAX_DECISION_TTL_MS
        and p['expires_at_ms'] <= e['review_expires_at_ms']
        and p['signed_at_ms'] <= now_ms < p['expires_at_ms'])
    checks['quote_observed_and_delivered_before_decision'] = (
        e['quote_observed_at_ms'] <= e['quote_received_at_ms'] <= p['signed_at_ms'])
    checks['quote_fresh_at_decision_and_now'] = (
        checks['quote_observed_and_delivered_before_decision']
        and now_ms - e['quote_observed_at_ms'] <= MAX_QUOTE_AGE_MS)
    checks['quote_transport_within_limit'] = (
        checks['quote_observed_and_delivered_before_decision']
        and e['quote_received_at_ms'] - e['quote_observed_at_ms'] <= MAX_TRANSPORT_MS)
    checks['nonce_not_in_declared_used_snapshot'] = p['nonce'] not in used_nonces
    checks['kill_switch_inactive'] = not kill_switch_active
    checks['reconciliation_declared_healthy'] = reconciliation_healthy

    audit_digest = hashlib.sha256(json.dumps({
        'schema': SCHEMA, 'payload': p, 'signature_hex': decision['signature_hex'],
        'expected': e, 'now_ms': now_ms, 'checks': checks,
    }, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode('ascii')).hexdigest()
    return {
        'schema': SCHEMA,
        'status': 'HOLD_RECONCILIATION',
        'checks': checks,
        'failed_checks': [name for name, ok in checks.items() if not ok],
        'declared_evidence_checks_pass': all(checks.values()),
        'audit_sha256': audit_digest,
        'signature_valid': signature_valid,
        'owner_identity_authenticated': False,
        'broker_inventory_authenticated': False,
        'quote_authenticated': False,
        'nonce_durably_reserved_or_consumed': False,
        'human_presence_verified': False,
        'order_specific_approval_durably_recorded': False,
        'may_execute_paper_order': False,
        'may_execute_real_order': False,
        'warnings': [
            'A valid signature proves key possession, not human presence or uncompromised owner consent.',
            'The expected review, policy, inventory, public key and used-nonce snapshot are not authenticated by this function.',
            'No atomic replay prevention, broker reconciliation, order reservation or execution exists.',
            'Any order/quote/risk change needs a new signed decision; all execution stays disabled.',
        ],
    }
