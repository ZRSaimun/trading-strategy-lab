"""Disconnected, read-only concentration overlay for the paper exposure guard.

Group definitions are caller-declared and NOT verified as instrument equivalence.
No persistence, brokerage connection, approval, or order authorization.
"""
from decimal import Decimal, localcontext
import re

from app.paper_account_exposure_guard import evaluate_paper_account_exposure

_GROUP = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,63}\Z')
_AMOUNT = re.compile(r'(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,8})?\Z')
_POLICY_KEYS = {'instrument_groups', 'group_notional_caps_cash', 'max_group_share_of_stressed_equity'}
_MAX = Decimal('1000000000000000')


def _cash(value, label, *, maximum=_MAX):
    if type(value) is not str or not _AMOUNT.fullmatch(value):
        raise ValueError(f'{label} must be a bounded decimal string')
    number = Decimal(value)
    if number <= 0 or number > maximum:
        raise ValueError(f'{label} outside bounds')
    return number


def _group(value):
    if type(value) is not str or not _GROUP.fullmatch(value):
        raise ValueError('Invalid group alias')
    return value


def evaluate_grouped_paper_exposure(snapshot: dict, group_policy: dict, *, now_ms: int) -> dict:
    """Re-evaluate the original account guard, then enforce declared group caps.

    Missing instrument mappings fail closed; group caps and stress-equity share
    must both pass. The result NEVER grants permission to submit orders.
    """
    base = evaluate_paper_account_exposure(snapshot, now_ms=now_ms)
    if type(group_policy) is not dict or set(group_policy) != _POLICY_KEYS:
        raise ValueError('Group policy has missing or unexpected fields')
    mapping = group_policy['instrument_groups']
    caps = group_policy['group_notional_caps_cash']
    if type(mapping) is not dict or type(caps) is not dict:
        raise ValueError('Group mappings and caps must be dictionaries')
    if len(mapping) > 500 or len(caps) > 500:
        raise ValueError('Group policy exceeds bounds')
    instruments = {row['instrument'] for row in snapshot['exposures']}
    if set(mapping) != instruments:
        raise ValueError('Every instrument must have exactly one declared group')
    for symbol, group in mapping.items():
        if type(symbol) is not str:
            raise ValueError('Invalid instrument mapping key')
        _group(group)
    if set(caps) != set(mapping.values()):
        raise ValueError('Every declared group must have exactly one cap')
    validated_caps = {_group(group): _cash(cap, 'Group cap') for group, cap in caps.items()}
    fraction = _cash(group_policy['max_group_share_of_stressed_equity'],
                     'Stressed-equity group fraction', maximum=Decimal('1'))
    totals = {group: Decimal(0) for group in validated_caps}
    with localcontext() as ctx:
        ctx.prec = 80
        if len(snapshot['exposures']) != len(base['exposures']):
            raise ValueError('Exposure audit length mismatch')
        for row, detail in zip(snapshot['exposures'], base['exposures']):
            totals[mapping[row['instrument']]] += Decimal(detail['gross_notional_cash'])
        stressed_equity = Decimal(base['stressed_equity_cash'])
        cap_ok = all(total <= validated_caps[group] for group, total in totals.items())
        share_ok = stressed_equity > 0 and all(
            total <= stressed_equity * fraction for total in totals.values()
        )
    out = dict(base)
    out['checks'] = dict(base['checks'])
    out['checks']['declared_group_notional_within_cap'] = cap_ok
    out['checks']['declared_group_stressed_equity_share_within_cap'] = share_ok
    out['failed_checks'] = sorted(k for k, passed in out['checks'].items() if not passed)
    out['status'] = ('ASSUMPTIONS_WITHIN_LIMITS_UNVERIFIED'
                     if not out['failed_checks'] else 'HOLD_RECONCILIATION')
    out['declared_group_notional_cash'] = {group: format(totals[group], 'f')
                                            for group in sorted(totals)}
    out['group_mapping_authenticated'] = False
    out['may_execute_paper_order'] = False
    out['may_execute_real_order'] = False
    out['warnings'] = list(base['warnings']) + [
        'Instrument-to-group mappings are unverified owner assertions, not broker-proven equivalence or correlation.',
        'Unmapped aliases and omitted positions may evade declared group concentration; no execution is authorized.',
    ]
    return out
