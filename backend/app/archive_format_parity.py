"""Read-only, streaming HistData ASCII-vs-MetaTrader M1 wall-clock price parity.

No timezone, vendor authenticity, licensing, spread, volume or execution
claims are made. Exact decimal OHLC is compared only at equal naive minute
stamps; no source rows are repaired, reordered, extracted or imported.
"""

import argparse
import csv
from decimal import Decimal, InvalidOperation
import io
import json
import re
import zipfile
from datetime import datetime
from pathlib import Path


class ParityInputError(ValueError):
    """Input cannot support an unambiguous source-preserving comparison."""


def _rows(path, fmt, counters, *, max_rows, max_uncompressed_bytes):
    """Yield monotonic (wall-minute, OHLC) rows from exactly one CSV member."""
    with zipfile.ZipFile(path) as archive:
        members = [m for m in archive.infolist() if not m.is_dir()]
        if len(archive.infolist()) > 1000 or len(members) != 1:
            raise ParityInputError('exactly one non-directory CSV member required')
        member = members[0]
        if not member.filename.lower().endswith('.csv'):
            raise ParityInputError('unsupported ZIP member')
        if member.file_size > max_uncompressed_bytes:
            raise ParityInputError('uncompressed byte budget exceeded')
        previous = None
        with archive.open(member) as binary:
            reader = csv.reader(io.TextIOWrapper(binary, encoding='utf-8-sig', errors='strict', newline=''),
                                delimiter=';' if fmt == 'ascii' else ',')
            for row in reader:
                counters['rows'] += 1
                if counters['rows'] > max_rows:
                    raise ParityInputError('row budget exceeded')
                try:
                    if fmt == 'ascii':
                        if len(row) != 6:
                            raise ParityInputError('invalid ASCII column count')
                        if re.fullmatch(r'[0-9]{8} [0-9]{6}', row[0]) is None:
                            raise ParityInputError('noncanonical ASCII timestamp')
                        stamp = datetime.strptime(row[0], '%Y%m%d %H%M%S')
                        prices = row[1:5]
                        volume = row[5]
                    else:
                        if len(row) != 7:
                            raise ParityInputError('invalid MT column count')
                        if (re.fullmatch(r'[0-9]{4}\.[0-9]{2}\.[0-9]{2}', row[0]) is None
                                or re.fullmatch(r'[0-9]{2}:[0-9]{2}', row[1]) is None):
                            raise ParityInputError('noncanonical MT timestamp')
                        stamp = datetime.strptime(row[0] + ' ' + row[1], '%Y.%m.%d %H:%M')
                        prices = row[2:6]
                        volume = row[6]
                    if stamp.second or stamp.microsecond:
                        raise ParityInputError('non-minute timestamp')
                    values = tuple(Decimal(x) for x in prices)
                    vol = Decimal(volume)
                    if not all(x.is_finite() for x in (*values, vol)):
                        raise ParityInputError('non-finite OHLCV')
                    op, hi, lo, cl = values
                    if lo > min(op, cl) or hi < max(op, cl) or lo > hi or vol < 0:
                        raise ParityInputError('invalid OHLCV')
                    if previous is not None and stamp <= previous:
                        raise ParityInputError('duplicate or backward wall-clock timestamp')
                    previous = stamp
                    if vol == 0:
                        counters['zero_volume_rows'] += 1
                    yield stamp, values
                except (InvalidOperation, ValueError, OverflowError) as exc:
                    if isinstance(exc, ParityInputError):
                        raise ParityInputError(f'{fmt} row {reader.line_num}: {exc}') from exc
                    raise ParityInputError(f'{fmt} row {reader.line_num}: invalid timestamp or number') from exc
        if counters['rows'] == 0:
            raise ParityInputError('empty CSV member')


def compare_archives(ascii_zip, mt_zip, *, instrument, provider,
                     max_rows=20_000_000, max_uncompressed_bytes=2_000_000_000,
                     max_samples=20):
    """Compare two immutable ZIPs without extraction; never infer UTC offset.

    Returns aggregate-only observations, NOT a data-ingestion approval. An
    exception means the comparison is invalid, not that prices are equal.
    """
    if not isinstance(instrument, str) or not instrument.strip():
        raise ParityInputError('instrument identity required')
    if not isinstance(provider, str) or not provider.strip():
        raise ParityInputError('provider identity required')
    if any(not isinstance(x, int) or isinstance(x, bool) or x < 1
           for x in (max_rows, max_uncompressed_bytes)):
        raise ParityInputError('positive integer budgets required')
    if not isinstance(max_samples, int) or isinstance(max_samples, bool) or not 0 <= max_samples <= 100:
        raise ParityInputError('sample budget must be between 0 and 100')
    if Path(ascii_zip).resolve() == Path(mt_zip).resolve():
        raise ParityInputError('two distinct ZIP files required')

    left_count = {'rows': 0, 'zero_volume_rows': 0}
    right_count = {'rows': 0, 'zero_volume_rows': 0}
    result = {
        'instrument': instrument, 'provider': provider,
        'comparison': 'ASCII vs MT exact Decimal OHLC at identical naive wall-clock minutes',
        'timebase_verified': False, 'source_authenticity_verified': False,
        'usage_rights_verified': False, 'broker_execution_verified': False,
        'ascii_rows': 0, 'mt_rows': 0, 'ascii_zero_volume_rows': 0,
        'mt_zero_volume_rows': 0, 'aligned_minutes': 0, 'equal_ohlc_minutes': 0,
        'conflicting_ohlc_minutes': 0, 'ascii_only_minutes': 0,
        'mt_only_minutes': 0, 'samples': [], 'status': 'UNVERIFIED',
    }

    def next_or_none(iterator):
        return next(iterator, None)

    def sample(kind, stamp):
        if len(result['samples']) < max_samples:
            result['samples'].append({'kind': kind, 'wall_minute': stamp.strftime('%Y-%m-%d %H:%M')})

    a = _rows(ascii_zip, 'ascii', left_count, max_rows=max_rows,
              max_uncompressed_bytes=max_uncompressed_bytes)
    b = _rows(mt_zip, 'mt', right_count, max_rows=max_rows,
              max_uncompressed_bytes=max_uncompressed_bytes)
    try:
        x, y = next_or_none(a), next_or_none(b)
        while x is not None or y is not None:
            if y is None or (x is not None and x[0] < y[0]):
                result['ascii_only_minutes'] += 1
                sample('ascii_only', x[0])
                x = next_or_none(a)
            elif x is None or y[0] < x[0]:
                result['mt_only_minutes'] += 1
                sample('mt_only', y[0])
                y = next_or_none(b)
            else:
                result['aligned_minutes'] += 1
                if x[1] == y[1]:
                    result['equal_ohlc_minutes'] += 1
                else:
                    result['conflicting_ohlc_minutes'] += 1
                    sample('ohlc_conflict', x[0])
                x, y = next_or_none(a), next_or_none(b)
    finally:
        a.close()
        b.close()

    result['ascii_rows'] = left_count['rows']
    result['mt_rows'] = right_count['rows']
    result['ascii_zero_volume_rows'] = left_count['zero_volume_rows']
    result['mt_zero_volume_rows'] = right_count['zero_volume_rows']
    if result['conflicting_ohlc_minutes']:
        result['status'] = 'PRICE_CONFLICT'
    elif result['aligned_minutes'] == 0:
        result['status'] = 'NO_SHARED_WALL_CLOCK_MINUTES'
    elif result['ascii_only_minutes'] or result['mt_only_minutes']:
        result['status'] = 'PARTIAL_WALL_CLOCK_PARITY'
    else:
        result['status'] = 'EXACT_WALL_CLOCK_PRICE_PARITY'
    result['research_ready'] = False  # Parity is not proof of timebase, source or license.
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ascii_zip')
    parser.add_argument('mt_zip')
    parser.add_argument('--instrument', required=True)
    parser.add_argument('--provider', required=True)
    args = parser.parse_args(argv)
    report = compare_archives(args.ascii_zip, args.mt_zip,
                              instrument=args.instrument, provider=args.provider)
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
