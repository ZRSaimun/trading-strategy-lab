"""Read-only, bounded forensic manifest of nonadjacent HistData minute collisions.

Never repairs candles, infers UTC, imports prices or approves research.
Reuses the source-order parser in archive_duplicate_parity.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import zipfile

from .archive_duplicate_parity import ParityInputError, _records


def scan_archive_collisions(path, *, data_format, instrument, provider,
                            max_unique_minutes=500_000, max_rows=20_000_000,
                            max_uncompressed_bytes=2_000_000_000, sample_limit=30):
    """Return bounded metadata, never prices; reject if exact tracking exceeds budget.

    The first OHLC observation for each naive wall minute is held in memory
    solely to identify conflicting repeats. No canonical price is selected.
    """
    if data_format not in ('ascii', 'mt'):
        raise ParityInputError('Unsupported data format')
    if not isinstance(instrument, str) or not instrument or len(instrument) > 64 or not all(
            ch.isalnum() or ch in '._-' for ch in instrument):
        raise ParityInputError('Invalid instrument identity')
    if not isinstance(provider, str) or not provider or len(provider) > 64 or not all(
            ch.isalnum() or ch in '._- ' for ch in provider):
        raise ParityInputError('Invalid provider identity')
    if (any(type(n) is not int or n <= 0 for n in
            (max_unique_minutes, max_rows, max_uncompressed_bytes))
            or type(sample_limit) is not int or not 0 <= sample_limit <= 50):
        raise ParityInputError('Invalid resource budget')
    if not Path(path).is_file():
        raise ParityInputError('ZIP file not found')

    counters = dict(rows=0, adjacent_duplicate_minutes=0,
                    conflicting_adjacent_duplicate_ohlc=0, backward_jumps=0,
                    zero_volume_rows=0, vendor_status_report_present=False)
    # minute -> [first_ordinal, first_ohlc, already_repeated, already_conflicting]
    first = {}
    repeated_rows = conflicting_repeated_rows = collision_minutes = conflict_minutes = 0
    samples = []
    collision_days = {}
    first_collision_ordinal = last_collision_ordinal = None
    iterator = _records(path, data_format, counters, max_rows=max_rows,
                        max_uncompressed_bytes=max_uncompressed_bytes)
    try:
        for ordinal, (minute, prices) in enumerate(iterator, 1):
            observed = first.get(minute)
            if observed is None:
                if len(first) >= max_unique_minutes:
                    raise ParityInputError('Exact unique-minute budget exceeded; no partial report')
                first[minute] = [ordinal, prices, False, False]
                continue
            repeated_rows += 1
            if first_collision_ordinal is None:
                first_collision_ordinal = ordinal
            last_collision_ordinal = ordinal
            wall_day = minute.strftime('%Y-%m-%d')
            if wall_day not in collision_days:
                if len(collision_days) >= 3660:
                    raise ParityInputError('Collision day report budget exceeded; no partial report')
                collision_days[wall_day] = dict(repeated_rows=0, conflicting_repeated_rows=0,
                                                distinct_collision_minutes=0,
                                                distinct_conflicting_minutes=0)
            day = collision_days[wall_day]
            day['repeated_rows'] += 1
            if not observed[2]:
                day['distinct_collision_minutes'] += 1
                collision_minutes += 1
                observed[2] = True
            conflict = prices != observed[1]
            if conflict:
                conflicting_repeated_rows += 1
                day['conflicting_repeated_rows'] += 1
                if not observed[3]:
                    day['distinct_conflicting_minutes'] += 1
                    conflict_minutes += 1
                    observed[3] = True
            if len(samples) < sample_limit:
                samples.append({'wall_minute_unverified': minute.strftime('%Y-%m-%d %H:%M'),
                                'first_row_ordinal': observed[0],
                                'repeated_row_ordinal': ordinal,
                                'kind': 'OHLC_CONFLICT' if conflict else 'IDENTICAL_REPEAT'})
    finally:
        iterator.close()

    needs_quarantine = bool(repeated_rows or counters['backward_jumps'])
    return {
        'result': 'QUARANTINE_REQUIRED' if needs_quarantine else 'FORMAT_CHECK_ONLY_UNVERIFIED',
        'instrument': instrument, 'provider': provider, 'format': data_format,
        'source_order_rows': counters['rows'], 'distinct_wall_minutes': len(first),
        'repeated_rows': repeated_rows, 'collision_minutes': collision_minutes,
        'conflicting_repeated_rows_vs_first': conflicting_repeated_rows,
        'conflicting_collision_minutes': conflict_minutes,
        'backward_jumps': counters['backward_jumps'],
        'adjacent_duplicate_minutes': counters['adjacent_duplicate_minutes'],
        'vendor_status_report_present': counters['vendor_status_report_present'],
        'sampled_collision_locations': samples,
        'first_collision_row_ordinal': first_collision_ordinal,
        'last_collision_row_ordinal': last_collision_ordinal,
        'collision_counts_by_unverified_wall_day': [
            {'wall_day_unverified': key, **collision_days[key]} for key in sorted(collision_days)
        ],
        'first_observation_policy': 'Forensic comparison only; no canonical price selected',
        'timebase_verified': False, 'authenticity_verified': False,
        'usage_rights_verified': False, 'research_ready': False,
        'can_auto_import': False, 'live': False, 'may_execute_order': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--format', choices=('ascii', 'mt'), required=True)
    parser.add_argument('--instrument', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--max-unique-minutes', type=int, default=500_000)
    args = parser.parse_args(argv)
    try:
        report = scan_archive_collisions(args.archive, data_format=args.format,
                                         instrument=args.instrument, provider=args.provider,
                                         max_unique_minutes=args.max_unique_minutes)
    except (ParityInputError, OSError, ValueError, UnicodeError, csv.Error,
            zipfile.BadZipFile, RuntimeError):
        print(json.dumps({'result': 'REJECTED', 'research_ready': False,
                          'can_auto_import': False, 'live': False, 'may_execute_order': False}))
        return 2
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
