"""Offline external-checkpoint comparison for a paper broker submission ledger.

This is a read-only audit check, not an approval or an execution adapter.
The caller MUST authenticate the anchor independently of the ledger file.
"""
import hashlib
import json
import re

from .paper_submission_attempt_ledger import MAX_EVENTS, inspect_ledger

_HEX64 = re.compile(r'[0-9a-f]{64}\Z')
_MAX_AGE_MS = 86_400_000
_MAX_EPOCH_MS = 8_640_000_000_000_000
_FIELDS = frozenset({'schema', 'event_count', 'order_count', 'audit_tip_sha256',
                     'order_projection_sha256', 'recorded_at_ms'})


def projection_sha256(orders):
    """Canonical digest of the full, already-verified order projection."""
    return hashlib.sha256(json.dumps(orders, sort_keys=True, separators=(',', ':'),
                                     ensure_ascii=True).encode('ascii')).hexdigest()


def verify_external_anchor(path, *, anchor, now_ms, max_age_ms=300_000):
    """Require an exact externally trusted checkpoint; never authorize orders.

    A legitimate append after the checkpoint also fails closed until an
    independently verified new checkpoint is supplied.
    """
    if not isinstance(anchor, dict) or set(anchor) != _FIELDS:
        raise ValueError('Exact externally trusted anchor fields required')
    if anchor['schema'] != 'paper-submission-attempt-ledger-v1':
        raise ValueError('Unexpected ledger anchor schema')
    for field in ('event_count', 'order_count', 'recorded_at_ms'):
        value = anchor[field]
        if type(value) is not int or not 0 <= value <= (_MAX_EPOCH_MS if field == 'recorded_at_ms' else MAX_EVENTS):
            raise ValueError(f'Invalid anchor {field}')
    for field in ('audit_tip_sha256', 'order_projection_sha256'):
        if not isinstance(anchor[field], str) or not _HEX64.fullmatch(anchor[field]):
            raise ValueError(f'Invalid anchor {field}')
    if type(now_ms) is not int or not 0 <= now_ms <= _MAX_EPOCH_MS:
        raise ValueError('Invalid current time')
    if type(max_age_ms) is not int or not 0 < max_age_ms <= _MAX_AGE_MS:
        raise ValueError('Invalid maximum anchor age')
    age = now_ms - anchor['recorded_at_ms']
    if age < 0 or age > max_age_ms:
        raise ValueError('Future-dated or expired external anchor')
    ledger = inspect_ledger(path)
    # An authenticated checkpoint timestamp must not predate any locally
    # recorded event. Otherwise a forged future event clock could be anchored
    # as apparently fresh and obstruct later durable risk transitions.
    last_event_ms = ledger.get('last_recorded_at_ms')
    if ledger['event_count'] == 0:
        if last_event_ms is not None:
            raise ValueError('Empty ledger has an inconsistent event clock')
    elif (type(last_event_ms) is not int or not 0 <= last_event_ms <= _MAX_EPOCH_MS
          or last_event_ms > anchor['recorded_at_ms']):
        raise ValueError('Ledger event clock exceeds trusted checkpoint time')
    actual = {
        'schema': ledger['schema'],
        'event_count': ledger['event_count'],
        'order_count': ledger['order_count'],
        'audit_tip_sha256': ledger['audit_tip_sha256'],
        'order_projection_sha256': projection_sha256(ledger['orders']),
    }
    if any(actual[k] != anchor[k] for k in actual):
        raise ValueError('Ledger differs from independently anchored checkpoint')
    return {
        'status': 'HOLD_RECONCILIATION',
        'audit_tip_sha256': actual['audit_tip_sha256'],
        'event_count': actual['event_count'],
        'may_submit_paper_order': False,
        'may_submit_real_order': False,
        'requires_independent_reconciliation': True,
        'warning': 'Anchor authenticity and storage independence are caller responsibilities; matching is not trading authorization.',
    }
