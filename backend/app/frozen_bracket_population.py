"""Offline population-completeness gate for frozen M1 bracket research.

A matching SHA-256 is a consistency check, not proof of preregistration,
archive provenance, source rights, untouched holdout, or executable prices.
No network, persistence, order placement, or data imports.
"""
import hashlib
import json
import re
from decimal import Decimal

from app.ohlc_bracket_uncertainty import audit_paths

_PROTOCOL = 'm1-bracket-population-v1'
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_PRICE = re.compile(r'[+-]?\d{1,20}(?:\.\d{1,12})?\Z')
_SOURCE = ('instrument', 'provider', 'venue', 'archive_sha256', 'price_side', 'horizon_minutes')
_FROZEN = ('path_id', 'signal_at', 'direction', 'entry', 'stop', 'target')
_EXCLUDED = ('path_id', 'signal_at', 'reason')
_REASONS = frozenset({'PRE_SIGNAL_DATA_GAP', 'INVALID_PRE_SIGNAL_CONTEXT',
                      'OUTSIDE_FROZEN_ELIGIBILITY_WINDOW', 'SOURCE_UNAVAILABLE_BEFORE_SIGNAL'})
_MAX = 100000


def _fields(value, expected, label):
    if not isinstance(value, dict) or set(value) != set(expected):
        raise ValueError(f'{label} must contain exactly the frozen schema fields')


def _clock(value):
    return type(value) is int and 0 <= value <= 8640000000 and value % 60 == 0


def _price(value):
    if not isinstance(value, str) or not _PRICE.fullmatch(value):
        raise ValueError('Invalid frozen decimal price')
    return Decimal(value)


def _validate(manifest):
    _fields(manifest, ('protocol', 'source', 'eligible_signals', 'excluded_signals'), 'Manifest')
    if manifest['protocol'] != _PROTOCOL:
        raise ValueError('Unknown frozen protocol')
    source = manifest['source']
    _fields(source, _SOURCE, 'Source')
    for key in ('instrument', 'provider', 'venue'):
        if not isinstance(source[key], str) or not 1 <= len(source[key].strip()) <= 128:
            raise ValueError('Invalid exact source identity')
    if not isinstance(source['archive_sha256'], str) or not _SHA.fullmatch(source['archive_sha256']):
        raise ValueError('Invalid archive digest')
    if source['price_side'] not in ('BID', 'ASK', 'MID'):
        raise ValueError('Invalid price side')
    if type(source['horizon_minutes']) is not int or not 1 <= source['horizon_minutes'] <= 1440:
        raise ValueError('Invalid frozen horizon')
    eligible, excluded = manifest['eligible_signals'], manifest['excluded_signals']
    if not isinstance(eligible, list) or not isinstance(excluded, list) or not eligible or len(eligible) + len(excluded) > _MAX:
        raise ValueError('Bounded nonempty eligible population required')
    ids, clocks = set(), set()
    for kind, rows, fields in (('eligible', eligible, _FROZEN), ('excluded', excluded, _EXCLUDED)):
        for row in rows:
            _fields(row, fields, kind)
            if not isinstance(row['path_id'], str) or not _ID.fullmatch(row['path_id']):
                raise ValueError('Invalid frozen path ID')
            if not _clock(row['signal_at']):
                raise ValueError('Invalid frozen signal UTC minute')
            if row['path_id'] in ids or row['signal_at'] in clocks:
                raise ValueError('Duplicate or colliding frozen signal')
            ids.add(row['path_id'])
            clocks.add(row['signal_at'])
            if kind == 'excluded':
                if not isinstance(row['reason'], str) or row['reason'] not in _REASONS:
                    raise ValueError('Unrecognized pre-signal exclusion reason')
            else:
                if row['direction'] not in ('LONG', 'SHORT'):
                    raise ValueError('Invalid frozen direction')
                entry, stop, target = (_price(row[k]) for k in ('entry', 'stop', 'target'))
                if entry == 0 or not (stop < entry < target if row['direction'] == 'LONG' else target < entry < stop):
                    raise ValueError('Invalid frozen bracket')
    return eligible, excluded


def fingerprint_population_manifest(manifest):
    """Deterministic digest of source, eligible membership, and all exclusions.

    Sorting list order is canonical; modifying membership/parameters/reasons is not.
    The digest must be retained *externally before outcomes* to be meaningful.
    """
    eligible, excluded = _validate(manifest)
    canonical = {
        'protocol': _PROTOCOL,
        'source': manifest['source'],
        'eligible_signals': sorted(eligible, key=lambda r: (r['signal_at'], r['path_id'])),
        'excluded_signals': sorted(excluded, key=lambda r: (r['signal_at'], r['path_id'])),
    }
    payload = json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256):
    """Require every frozen eligible signal and immutable input to be present.

    This gate cannot prove that the registry was frozen before results were seen,
    that it lists *all* eligible signals, or that exclusions were legitimate.
    """
    eligible, excluded = _validate(manifest)
    if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
        raise ValueError('External expected SHA-256 required')
    digest = fingerprint_population_manifest(manifest)
    if digest != expected_manifest_sha256:
        raise ValueError('Frozen population manifest SHA-256 mismatch')
    if not isinstance(paths, list) or len(paths) != len(eligible):
        raise ValueError('Incomplete frozen eligible population')
    expected = {row['path_id']: row for row in eligible}
    seen = set()
    for path in paths:
        if not isinstance(path, dict) or not isinstance(path.get('path_id'), str):
            raise ValueError('Invalid outcome path')
        key = path['path_id']
        if key in seen or key not in expected:
            raise ValueError('Duplicate or unregistered outcome path')
        seen.add(key)
        for field in _FROZEN:
            if path.get(field) != expected[key][field] or type(path.get(field)) is not type(expected[key][field]):
                raise ValueError(f'Outcome path modified frozen field: {field}')
        for field in _SOURCE:
            if path.get(field) != manifest['source'][field] or type(path.get(field)) is not type(manifest['source'][field]):
                raise ValueError(f'Outcome path changed frozen source: {field}')
        if path.get('entry_at') != path['signal_at'] + 60 or type(path.get('entry_at')) is not int:
            raise ValueError('Outcome path changed next-minute entry clock')
    if seen != set(expected):
        raise ValueError('Incomplete frozen eligible population')
    # Deterministic order independent of caller-provided outcome path order.
    ordered = sorted(paths, key=lambda row: (row['signal_at'], row['path_id']))
    outcome = audit_paths(ordered)
    if excluded:
        # Upstream eligibility/exclusion decisions cannot be independently audited.
        # Suppress full-population mean estimates rather than hide excluded signals.
        for scenario in outcome['cost_scenarios']:
            scenario['population_mean_lower_net_r'] = None
            scenario['population_mean_upper_net_r'] = None
        outcome['status'] = 'UNVERIFIED_EXCLUSIONS'
    return {
        'protocol': _PROTOCOL,
        'manifest_sha256': digest,
        'eligible_signals': len(eligible),
        'declared_excluded_signals': len(excluded),
        'excluded_by_reason': {r: sum(x['reason'] == r for x in excluded) for r in sorted(_REASONS)},
        'outcome_audit': outcome,
        'complete_against_supplied_manifest': True,
        'externally_preregistered': False,
        'upstream_population_completeness_verified': False,
        'source_rights_and_utc_verified': False,
        'untouched_holdout_verified': False,
        'verified_profitability': False,
        'warning': 'Supplied manifest equality only; digest matching is not independent evidence of prior freeze, eligibility, source rights, or profitable execution.',
    }
