"""Offline audit of causally frozen next-M1-open *intents*, not broker orders.

An intent freezes direction/stop/target at signal close, never the unknown
following open. Missing/gapped entry observations and gap-through brackets
withhold full-population statistics rather than selecting surviving fills.
"""
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, localcontext

from app.ohlc_bracket_uncertainty import COST_BPS, evaluate_path

_PROTOCOL = 'frozen-next-open-intent-v1'
_SOURCE = ('instrument', 'provider', 'venue', 'archive_sha256', 'price_side', 'horizon_minutes')
_INTENT = ('path_id', 'signal_at', 'direction', 'stop', 'target')
_EXCLUSION = ('path_id', 'signal_at', 'reason')
_REASONS = frozenset({'PRE_SIGNAL_DATA_GAP', 'INVALID_PRE_SIGNAL_CONTEXT',
                      'OUTSIDE_FROZEN_ELIGIBILITY_WINDOW', 'SOURCE_UNAVAILABLE_BEFORE_SIGNAL'})
_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}\Z')
_SHA = re.compile(r'[0-9a-f]{64}\Z')
_DEC = re.compile(r'[+-]?\d{1,20}(?:\.\d{1,12})?\Z')
_MAX = 100000
_MAX_CLOCK = 8640000000


def _exact(obj, fields, label):
    if not isinstance(obj, dict) or set(obj) != set(fields):
        raise ValueError(f'{label} must have exactly the specified fields')


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_CLOCK and value % 60 == 0


def _decimal(value):
    if not isinstance(value, str) or not _DEC.fullmatch(value):
        raise ValueError('Bounded exact decimal string required')
    return Decimal(value)


def _validate(manifest):
    _exact(manifest, ('protocol', 'source', 'eligible_intents', 'excluded_signals'), 'Manifest')
    if manifest['protocol'] != _PROTOCOL:
        raise ValueError('Unknown intent protocol')
    source = manifest['source']
    _exact(source, _SOURCE, 'Source')
    for key in ('instrument', 'provider', 'venue'):
        if not isinstance(source[key], str) or not 1 <= len(source[key].strip()) <= 128:
            raise ValueError('Invalid source identity')
    if not isinstance(source['archive_sha256'], str) or not _SHA.fullmatch(source['archive_sha256']):
        raise ValueError('Invalid archive SHA-256')
    if source['price_side'] not in ('BID', 'ASK', 'MID'):
        raise ValueError('Invalid price side')
    if type(source['horizon_minutes']) is not int or not 1 <= source['horizon_minutes'] <= 1440:
        raise ValueError('Invalid horizon')
    eligible, excluded = manifest['eligible_intents'], manifest['excluded_signals']
    if (not isinstance(eligible, list) or not isinstance(excluded, list)
            or not eligible or len(eligible) + len(excluded) > _MAX):
        raise ValueError('Nonempty bounded intent population required')
    ids, clocks = set(), set()
    for kind, rows, fields in (('Intent', eligible, _INTENT), ('Exclusion', excluded, _EXCLUSION)):
        for row in rows:
            _exact(row, fields, kind)
            if not isinstance(row['path_id'], str) or not _ID.fullmatch(row['path_id']):
                raise ValueError('Invalid path ID')
            if not _clock(row['signal_at']) or row['signal_at'] + 60 > _MAX_CLOCK:
                raise ValueError('Invalid signal clock')
            if row['path_id'] in ids or row['signal_at'] in clocks:
                raise ValueError('Duplicate signal ID or minute')
            ids.add(row['path_id'])
            clocks.add(row['signal_at'])
            if kind == 'Exclusion':
                if row['reason'] not in _REASONS:
                    raise ValueError('Invalid pre-signal exclusion')
            else:
                if row['direction'] not in ('LONG', 'SHORT'):
                    raise ValueError('Invalid direction')
                stop, target = _decimal(row['stop']), _decimal(row['target'])
                if not (stop < target if row['direction'] == 'LONG' else target < stop):
                    raise ValueError('Stop and target not directionally ordered')
    return eligible, excluded


def fingerprint_next_open_intents(manifest):
    """Digest is a consistency check; independently timestamp it before outcomes."""
    eligible, excluded = _validate(manifest)
    canonical = dict(protocol=_PROTOCOL, source=manifest['source'],
                     eligible_intents=sorted(eligible, key=lambda r: (r['signal_at'], r['path_id'])),
                     excluded_signals=sorted(excluded, key=lambda r: (r['signal_at'], r['path_id'])))
    payload = json.dumps(canonical, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def _validate_bars(bars, entry_at, horizon):
    if not isinstance(bars, list) or len(bars) > horizon:
        raise ValueError('Invalid bounded M1 observation list')
    last = None
    for bar in bars:
        _exact(bar, ('at', 'open', 'high', 'low', 'close'), 'M1 bar')
        at = bar['at']
        if (not _clock(at) or at < entry_at or at >= entry_at + horizon * 60
                or (last is not None and at <= last)):
            raise ValueError('Invalid, pre-entry, out-of-window or nonmonotonic M1 clock')
        last = at
        o, h, l, c = (_decimal(bar[k]) for k in ('open', 'high', 'low', 'close'))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError('Invalid M1 OHLC envelope')


def audit_next_open_intents(manifest, observations, expected_manifest_sha256):
    """Evaluate every declared intent without preregistering a future open.

    `observations` contain ONLY path_id and bars, never a user-chosen entry.
    Unobserved first M1 open or opening outside the frozen bracket is unresolved,
    not silently excluded from the denominator. No executable fills are implied.
    """
    eligible, excluded = _validate(manifest)
    if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
        raise ValueError('External expected manifest SHA-256 required')
    digest = fingerprint_next_open_intents(manifest)
    if digest != expected_manifest_sha256:
        raise ValueError('Frozen intent SHA-256 mismatch')
    if not isinstance(observations, list) or len(observations) != len(eligible):
        raise ValueError('Incomplete frozen intent observations')
    supplied = {}
    expected = {intent['path_id']: intent for intent in eligible}
    for row in observations:
        _exact(row, ('path_id', 'bars'), 'Observation')
        key = row['path_id']
        if not isinstance(key, str) or key not in expected or key in supplied:
            raise ValueError('Duplicate or unregistered intent observation')
        intent = expected[key]
        _validate_bars(row['bars'], intent['signal_at'] + 60, manifest['source']['horizon_minutes'])
        supplied[key] = row['bars']
    if set(supplied) != set(expected):
        raise ValueError('Missing intent observations')
    paths = []
    weeks = set()
    counts = {key: 0 for key in ('DETERMINATE', 'AMBIGUOUS', 'CENSORED',
                                 'UNOBSERVED_NEXT_OPEN', 'GAPPED_BRACKET_UNRESOLVED')}
    for intent in sorted(eligible, key=lambda r: (r['signal_at'], r['path_id'])):
        key, at = intent['path_id'], intent['signal_at']
        weeks.add(datetime.fromtimestamp(at, timezone.utc).isocalendar()[:2])
        bars = supplied[key]
        base = dict(path_id=key, signal_at=at, status=None, entry_observed=None,
                    lower_gross_r=None, upper_gross_r=None, cost_scenarios=[], reason=None)
        if not bars or bars[0]['at'] != at + 60:
            base.update(status='UNOBSERVED_NEXT_OPEN', reason='NEXT_MINUTE_OPEN_NOT_OBSERVED')
        else:
            entry = _decimal(bars[0]['open'])
            stop, target = _decimal(intent['stop']), _decimal(intent['target'])
            base['entry_observed'] = str(entry)
            inside = stop < entry < target if intent['direction'] == 'LONG' else target < entry < stop
            if entry == 0 or not inside:
                base.update(status='GAPPED_BRACKET_UNRESOLVED', reason='OPEN_OUTSIDE_FROZEN_BRACKET')
            else:
                path = dict(manifest['source'], **intent, entry_at=at + 60,
                            entry=str(entry), bars=bars)
                evaluated = evaluate_path(path)
                base.update(status=evaluated['status'], reason=evaluated['reason'],
                            lower_gross_r=evaluated['lower_gross_r'],
                            upper_gross_r=evaluated['upper_gross_r'],
                            cost_scenarios=evaluated['cost_scenarios'])
        counts[base['status']] += 1
        paths.append(base)
    unresolved = sum(counts[k] for k in ('CENSORED', 'UNOBSERVED_NEXT_OPEN',
                                        'GAPPED_BRACKET_UNRESOLVED'))
    sufficient = len(paths) >= 30 and len(weeks) >= 12
    reportable = not excluded and unresolved == 0 and sufficient
    if excluded:
        status = 'UNVERIFIED_EXCLUSIONS'
    elif unresolved:
        status = 'UNRESOLVED_ENTRIES_OR_OUTCOMES'
    elif not sufficient:
        status = 'INSUFFICIENT_SAMPLE'
    else:
        status = 'DESCRIPTIVE_BOUNDS_ONLY'
    scenarios = []
    for index, bps in enumerate(COST_BPS):
        lower = upper = None
        if reportable:
            with localcontext() as ctx:
                ctx.prec = 50
                lower = str(sum(Decimal(row['cost_scenarios'][index]['lower_net_r']) for row in paths) / len(paths))
                upper = str(sum(Decimal(row['cost_scenarios'][index]['upper_net_r']) for row in paths) / len(paths))
        scenarios.append(dict(additional_round_trip_bps=bps,
                              population_mean_lower_net_r=lower,
                              population_mean_upper_net_r=upper))
    return dict(protocol=_PROTOCOL, manifest_sha256=digest, status=status,
                eligible_intents=len(eligible), declared_excluded_signals=len(excluded),
                counts=counts, active_utc_weeks=len(weeks), cost_scenarios=scenarios,
                paths=paths, complete_against_supplied_manifest=True,
                future_open_preregistered=False, externally_preregistered=False,
                upstream_eligibility_verified=False, source_rights_and_utc_verified=False,
                untouched_holdout_verified=False, executable_broker_fills=False,
                verified_profitability=False,
                warning='Only self-supplied M1 BID/ASK/MID observations. Gap-through and missing next-open outcomes withhold means. Digest alone does not prove pre-outcome registration, source rights, executable fills or profitability.')
