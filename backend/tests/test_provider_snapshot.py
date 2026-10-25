"""Offline source-snapshot consistency tests; no paid calls or real quotes."""
import json

import pytest

from app.provider_snapshot import verify_normalized_snapshot


ROWS = [{'time': 60, 'open': 100.0, 'high': 102.0,
         'low': 99.0, 'close': 101.0, 'volume': None}]
SNAPSHOT = {
    'meta': {'symbol': 'XAU/USD', 'interval': '1min', 'exchange_timezone': 'UTC'},
    'values': [{'time': '1970-01-01T00:01:00+00:00',
                'open': '100', 'high': '102', 'low': '99', 'close': '101'}],
}


def encoded(value):
    return json.dumps(value, separators=(',', ':')).encode()


def test_exact_snapshot_matches_normalized_rows_without_mutation():
    before = encoded(SNAPSHOT)
    rows_before = [dict(row) for row in ROWS]
    assert verify_normalized_snapshot(ROWS, before, 'XAU/USD') is None
    assert ROWS == rows_before
    assert encoded(SNAPSHOT) == before


@pytest.mark.parametrize('mutate', [
    lambda s: s['meta'].update(symbol='XAG/USD'),
    lambda s: s['meta'].update(exchange_timezone='Europe/London'),
    lambda s: s['values'].clear(),
    lambda s: s['values'][0].update(time='1970-01-01T00:02:00+00:00'),
    lambda s: s['values'][0].update(time='1970-01-01T00:01:00'),
    lambda s: s['values'][0].update(high='103'),
    lambda s: s['values'][0].update(close='nan'),
    lambda s: s['values'][0].update(volume='5'),
])
def test_source_snapshot_mismatch_rejected(mutate):
    snapshot = json.loads(encoded(SNAPSHOT))
    mutate(snapshot)
    with pytest.raises(ValueError):
        verify_normalized_snapshot(ROWS, encoded(snapshot), 'XAU/USD')


@pytest.mark.parametrize('archive', [b'', b'{broken', b'[]', b'null', b'{}', b' ' * 3_000_001])
def test_bad_archive_structure_and_size_rejected(archive):
    with pytest.raises(ValueError):
        verify_normalized_snapshot(ROWS, archive, 'XAU/USD')


@pytest.mark.parametrize('changed', [
    {'close': 101.5},
    {'volume': 5.0},
    {'time': 120},
])
def test_changed_normalized_rows_rejected(changed):
    with pytest.raises(ValueError):
        verify_normalized_snapshot([{**ROWS[0], **changed}], encoded(SNAPSHOT), 'XAU/USD')


def test_duplicate_source_json_keys_are_rejected_at_every_depth():
    # Python's default JSON parser silently keeps the last duplicate key.
    original = encoded(SNAPSHOT)
    ambiguous = [
        original.replace(b'"meta":', b'"meta":{},"meta":', 1),
        original.replace(b'"symbol":', b'"symbol":"XAG/USD","symbol":', 1),
        original.replace(b'"close":', b'"close":"999","close":', 1),
    ]
    for archive in ambiguous:
        with pytest.raises(ValueError):
            verify_normalized_snapshot(ROWS, archive, 'XAU/USD')


@pytest.mark.parametrize('constant', [b'NaN', b'Infinity', b'-Infinity'])
def test_nonstandard_json_numeric_constants_rejected(constant):
    archive = encoded(SNAPSHOT).replace(b'"close":"101"', b'"close":' + constant, 1)
    with pytest.raises(ValueError):
        verify_normalized_snapshot(ROWS, archive, 'XAU/USD')
