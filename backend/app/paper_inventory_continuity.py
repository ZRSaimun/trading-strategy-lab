"""Disconnected, fail-closed continuity audit for declared PAPER risk snapshots.

No broker evidence, durable order reservation, approval or order execution.
Any inventory mutation requires independent authenticated reconciliation.
"""
import hashlib
import json

from .paper_account_exposure_guard import evaluate_paper_account_exposure

_MAX_MS = 8_640_000_000_000_000
_RISK_TERMS = frozenset({
    'instrument', 'provider', 'venue', 'side', 'quantity', 'entry_price',
    'stop_price', 'stressed_exit_price', 'point_value_cash',
    'estimated_total_cost_cash', 'margin_rate_percent',
})


def audit_paper_inventory_continuity(previous: dict, current: dict, *,
                                     previous_now_ms: int, now_ms: int) -> dict:
    """Compare complete caller-declared risk snapshots; never grant execution.

    A disappearing, added or modified order is NOT treated as settled, even if
    a cancellation was requested. No inferred fills or released risk budget.
    """
    for label, value in (('previous_now_ms', previous_now_ms), ('now_ms', now_ms)):
        if type(value) is not int or not 0 <= value <= _MAX_MS:
            raise ValueError(f'Invalid {label}')
    if now_ms <= previous_now_ms:
        raise ValueError('Snapshot clocks must strictly increase')
    # The existing evaluator strictly validates every field, rejects extra
    # fields/secrets, and performs its own independent risk checks.
    before = evaluate_paper_account_exposure(previous, now_ms=previous_now_ms)
    after = evaluate_paper_account_exposure(current, now_ms=now_ms)
    prior_rows = {row['client_order_id']: row for row in previous['exposures']}
    new_rows = {row['client_order_id']: row for row in current['exposures']}
    common = prior_rows.keys() & new_rows.keys()
    removed = prior_rows.keys() - new_rows.keys()
    added = new_rows.keys() - prior_rows.keys()
    altered = sum(any(a[key] != b[key] for key in _RISK_TERMS)
                  for a, b in ((prior_rows[key], new_rows[key]) for key in common))
    changed_state = sum(prior_rows[key]['state'] != new_rows[key]['state'] for key in common)
    replayed_quote = sum(
        new_rows[key]['quote_observed_at_ms'] <= prior_rows[key]['quote_observed_at_ms']
        or new_rows[key]['quote_received_at_ms'] <= prior_rows[key]['quote_received_at_ms']
        for key in common
    )
    policy_keys = [key for key in previous if key.startswith('max_')]
    checks = {
        'previous_risk_within_declared_limits': before['status'] == 'ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED',
        'current_risk_within_declared_limits': after['status'] == 'ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED',
        'account_identity_unchanged': (previous['account_id'] == current['account_id']
                                       and previous['currency'] == current['currency']),
        'risk_policy_unchanged': all(previous[key] == current[key] for key in policy_keys),
        'emergency_latch_not_cleared': not (previous['emergency_latched'] and not current['emergency_latched']),
        'cash_and_realized_pnl_unchanged': (previous['equity_cash'] == current['equity_cash']
                                           and previous['daily_realized_pnl_cash'] == current['daily_realized_pnl_cash']),
        'observation_interval_within_60s': now_ms - previous_now_ms <= 60_000,
        'unique_order_ids_in_both': (len(prior_rows) == len(previous['exposures'])
                                      and len(new_rows) == len(current['exposures'])),
        'no_unverified_order_disappearance': not removed,
        'no_unreserved_order_addition': not added,
        'order_risk_terms_unchanged': altered == 0,
        'order_state_unchanged_without_broker_receipt': changed_state == 0,
        'quote_clocks_advanced': replayed_quote == 0,
    }
    # A digest is a correlation identifier, NOT a signature or owner consent.
    payload = json.dumps({'previous': previous, 'current': current,
                          'previous_now_ms': previous_now_ms, 'now_ms': now_ms},
                         sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return {
        'status': 'CONTINUITY_ONLY_UNVERIFIED' if all(checks.values()) else 'HOLD_RECONCILIATION',
        'checks': checks,
        'failed_checks': sorted(key for key, passed in checks.items() if not passed),
        'removed_order_count': len(removed),
        'added_order_count': len(added),
        'altered_risk_terms_count': altered,
        'changed_order_state_count': changed_state,
        'replayed_quote_count': replayed_quote,
        'diagnostic_sha256': hashlib.sha256(payload.encode('ascii')).hexdigest(),
        'broker_authenticated': False,
        'inventory_complete_verified': False,
        'terminal_receipts_verified': False,
        'risk_reservations_committed': False,
        'owner_order_approval_verified': False,
        'may_execute_paper_order': False,
        'may_execute_real_order': False,
        'warnings': [
            'Declared snapshots do not prove complete broker inventory or fills.',
            'Removed, added, modified or state-changing orders require independent broker reconciliation.',
            'No risk reservation, broker connection, order sender or owner approval is provided.',
        ],
    }
