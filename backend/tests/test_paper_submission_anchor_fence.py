"""Offline, synthetic external-checkpoint tests. No broker network or orders."""
import pytest

from app import paper_submission_anchor_fence as fence


@pytest.fixture
def ledger(monkeypatch):
    state = {
        'schema': 'paper-submission-attempt-ledger-v1',
        'event_count': 2,
        'order_count': 1,
        'audit_tip_sha256': 'a' * 64,
        'orders': [{'broker': 'PAPER-LOCAL', 'account_alias': 'demo',
                    'client_order_id': 'o-1', 'status': 'ATTEMPT_UNKNOWN'}],
    }
    monkeypatch.setattr(fence, 'inspect_ledger', lambda path: state)
    anchor = {k: state[k] for k in ('schema', 'event_count', 'order_count', 'audit_tip_sha256')}
    anchor.update(order_projection_sha256=fence.projection_sha256(state['orders']), recorded_at_ms=1000)
    return state, anchor


def verify(anchor):
    return fence.verify_external_anchor('/no/network', anchor=anchor, now_ms=1001)


def test_matching_anchor_is_still_hold(ledger):
    result = verify(ledger[1])
    assert result['status'] == 'HOLD_RECONCILIATION'
    assert result['may_submit_real_order'] is False
    assert result['may_submit_paper_order'] is False


@pytest.mark.parametrize('field,value', [
    ('event_count', 1), ('order_count', 0), ('audit_tip_sha256', 'b'*64),
    ('order_projection_sha256', 'b'*64), ('schema', 'unknown'),
])
def test_mismatch_fails_closed(ledger, field, value):
    anchor = ledger[1].copy()
    anchor[field] = value
    with pytest.raises(ValueError):
        verify(anchor)


@pytest.mark.parametrize('field,value', [
    ('event_count', True), ('order_count', -1), ('recorded_at_ms', '1000'),
    ('audit_tip_sha256', 'A'*64), ('order_projection_sha256', 'bad'),
])
def test_malformed_anchor_fails_closed(ledger, field, value):
    anchor = ledger[1].copy()
    anchor[field] = value
    with pytest.raises(ValueError):
        verify(anchor)


def test_extra_and_missing_fields_fail_closed(ledger):
    with pytest.raises(ValueError):
        verify(ledger[1] | {'untrusted': 1})
    anchor = ledger[1].copy()
    del anchor['event_count']
    with pytest.raises(ValueError):
        verify(anchor)


def test_future_expired_and_bad_clock_fail_closed(ledger):
    anchor = ledger[1]
    for now in (999, 301001, True, -1, '1001'):
        with pytest.raises(ValueError):
            fence.verify_external_anchor('x', anchor=anchor, now_ms=now)
    for age in (0, -1, True, 86_400_001):
        with pytest.raises(ValueError):
            fence.verify_external_anchor('x', anchor=anchor, now_ms=1001, max_age_ms=age)


def test_append_after_anchor_fails_closed(ledger):
    state, anchor = ledger
    state['event_count'] += 1
    with pytest.raises(ValueError, match='differs'):
        verify(anchor)


def test_projection_tampering_fails_closed(ledger):
    state, anchor = ledger
    state['orders'][0]['status'] = 'RECONCILED_FILLED'
    with pytest.raises(ValueError, match='differs'):
        verify(anchor)


def test_inspection_failure_propagates(ledger, monkeypatch):
    def failed(path):
        raise ValueError('Ledger hash mismatch')
    monkeypatch.setattr(fence, 'inspect_ledger', failed)
    with pytest.raises(ValueError, match='hash mismatch'):
        verify(ledger[1])


def test_projection_digest_is_deterministic():
    a = [{'broker': 'PAPER-LOCAL', 'status': 'PREPARED'}]
    b = [{'status': 'PREPARED', 'broker': 'PAPER-LOCAL'}]
    assert fence.projection_sha256(a) == fence.projection_sha256(b)
