"""Offline, duplicate-aware ASCII/MT HistData ZIP row-sequence comparison.

Identical rows (including anomalies) do not establish authentic prices, a verified
source clock, market coverage, rights, or backtest eligibility. Never imports data.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime
from decimal import Decimal, InvalidOperation
import io
import json
from pathlib import Path
import re
import stat
import zipfile


class ParityInputError(ValueError):
    """Untrusted ZIP cannot support a bounded, unambiguous comparison."""


def _records(path, fmt, counts, *, max_rows, max_uncompressed_bytes):
    """Yield original-order naive wall minutes and exact OHLC decimals.

    Deliberately preserve repeated and backward timestamps for forensic review.
    One flat CSV plus an optional flat vendor .txt status report is allowed;
    no archive paths are extracted. Status text is untrusted and never used
    to validate prices or override candle observations.
    """
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not 1 <= len(members) <= 2:
            raise ParityInputError('Expected one CSV and optional TXT status report')
        for item in members:
            mode = (item.external_attr >> 16) & 0o170000
            if (item.is_dir()
                    or not re.fullmatch(r'[A-Za-z0-9_.()\-]+\.(?:csv|txt)', item.filename, re.I)
                    or mode not in (0, stat.S_IFREG)
                    or item.flag_bits & 1):
                raise ParityInputError('Unsupported, encrypted or link ZIP member')
        csv_members = [item for item in members if item.filename.lower().endswith('.csv')]
        txt_members = [item for item in members if item.filename.lower().endswith('.txt')]
        if len(csv_members) != 1 or len(txt_members) > 1:
            raise ParityInputError('Expected one CSV and at most one TXT status report')
        member = csv_members[0]
        if member.file_size > max_uncompressed_bytes:
            raise ParityInputError('Uncompressed byte budget exceeded')
        if txt_members:
            # Actual HistData downloads include a small text gap-status report.
            # Consume it to check its CRC, but never trust its gap assertions.
            report = txt_members[0]
            if report.file_size > 32768:
                raise ParityInputError('TXT status report exceeds byte budget')
            with archive.open(report) as status_stream:
                report_bytes = 0
                while chunk := status_stream.read(4096):
                    report_bytes += len(chunk)
                    if report_bytes > 32768:
                        raise ParityInputError('TXT status report exceeds byte budget')
        counts['vendor_status_report_present'] = bool(txt_members)
        previous = None
        previous_prices = None
        with archive.open(member) as raw:
            with io.TextIOWrapper(raw, encoding='utf-8-sig', errors='strict', newline='') as stream:
                def bounded_lines():
                    # Iterating over TextIOWrapper allocates an entire physical
                    # line before checking its length. Bound the read itself.
                    while True:
                        line = stream.readline(1025)
                        if not line:
                            break
                        if len(line) > 1024 or (len(line) == 1024 and
                                               not line.endswith(('\n', '\r'))):
                            raise ParityInputError('CSV line exceeds limit')
                        yield line
                # HistData is unquoted CSV. Disallow multiline quoted fields,
                # which otherwise evade the per-physical-line size budget.
                reader = csv.reader(bounded_lines(),
                                    delimiter=';' if fmt == 'ascii' else ',',
                                    quoting=csv.QUOTE_NONE, strict=True)
                for line_number, row in enumerate(reader, 1):
                    counts['rows'] += 1
                    if counts['rows'] > max_rows:
                        raise ParityInputError('Row budget exceeded')
                    try:
                        if fmt == 'ascii':
                            if len(row) != 6 or not re.fullmatch(r'[0-9]{8} [0-9]{6}', row[0]):
                                raise ParityInputError('Invalid ASCII columns/timestamp')
                            stamp = datetime.strptime(row[0], '%Y%m%d %H%M%S')
                            raw_prices, volume = row[1:5], row[5]
                        else:
                            if (len(row) != 7 or not re.fullmatch(r'[0-9]{4}\.[0-9]{2}\.[0-9]{2}', row[0])
                                    or not re.fullmatch(r'[0-9]{2}:[0-9]{2}', row[1])):
                                raise ParityInputError('Invalid MT columns/timestamp')
                            stamp = datetime.strptime(row[0] + ' ' + row[1], '%Y.%m.%d %H:%M')
                            raw_prices, volume = row[2:6], row[6]
                        if stamp.second or stamp.microsecond:
                            raise ParityInputError('Non-minute timestamp')
                        prices = tuple(Decimal(v) for v in raw_prices)
                        vol = Decimal(volume)
                        op, hi, lo, cl = prices
                        if (not all(v.is_finite() for v in (*prices, vol))
                                or lo > min(op, cl) or hi < max(op, cl) or lo > hi or vol < 0):
                            raise ParityInputError('Invalid OHLCV')
                    except (ValueError, InvalidOperation, OverflowError) as exc:
                        raise ParityInputError(f'Invalid {fmt} row {line_number}') from exc
                    if previous is not None:
                        if stamp == previous:
                            counts['adjacent_duplicate_minutes'] += 1
                            if prices != previous_prices:
                                counts['conflicting_adjacent_duplicate_ohlc'] += 1
                        elif stamp < previous:
                            counts['backward_jumps'] += 1
                    previous, previous_prices = stamp, prices
                    if vol == 0:
                        counts['zero_volume_rows'] += 1
                    yield stamp, prices
        if counts['rows'] == 0:
            raise ParityInputError('Empty CSV')


def compare_duplicate_archives(ascii_zip, mt_zip, *, instrument, provider,
                               max_rows=20_000_000, max_uncompressed_bytes=2_000_000_000,
                               sample_limit=10):
    """Compare exact row order, including repeated timestamps; never repair rows."""
    if not isinstance(instrument, str) or not re.fullmatch(r'[A-Za-z0-9_.\-]{1,64}', instrument):
        raise ParityInputError('Exact instrument identity required')
    if not isinstance(provider, str) or not re.fullmatch(r'[A-Za-z0-9_. \-]{1,64}', provider):
        raise ParityInputError('Exact provider identity required')
    if (any(type(v) is not int or v <= 0 for v in (max_rows, max_uncompressed_bytes))
            or type(sample_limit) is not int or not 0 <= sample_limit <= 50):
        raise ParityInputError('Invalid resource budget')
    if Path(ascii_zip).resolve() == Path(mt_zip).resolve():
        raise ParityInputError('Two distinct ZIP paths required')
    def counters():
        return dict(rows=0, adjacent_duplicate_minutes=0,
                    conflicting_adjacent_duplicate_ohlc=0, backward_jumps=0,
                    zero_volume_rows=0, vendor_status_report_present=False)
    a, b = counters(), counters()
    compared = equal = timestamp_mismatch = price_mismatch = 0
    samples = []
    left = _records(ascii_zip, 'ascii', a, max_rows=max_rows,
                    max_uncompressed_bytes=max_uncompressed_bytes)
    right = _records(mt_zip, 'mt', b, max_rows=max_rows,
                     max_uncompressed_bytes=max_uncompressed_bytes)
    try:
        while True:
            x, y = next(left, None), next(right, None)
            if x is None and y is None:
                break
            compared += 1
            if x is None or y is None:
                kind = 'ROW_COUNT_MISMATCH'
            elif x[0] != y[0]:
                timestamp_mismatch += 1
                kind = 'WALL_MINUTE_MISMATCH'
            elif x[1] != y[1]:
                price_mismatch += 1
                kind = 'OHLC_MISMATCH'
            else:
                equal += 1
                continue
            if len(samples) < sample_limit:
                samples.append({'row_ordinal': compared, 'kind': kind})
    finally:
        left.close()
        right.close()
    same = (a['rows'] == b['rows'] == compared == equal)
    anomalies = any(a[k] or b[k] for k in (
        'adjacent_duplicate_minutes', 'conflicting_adjacent_duplicate_ohlc', 'backward_jumps'))
    return {
        'result': ('EXACT_ROW_SEQUENCE_WITH_ANOMALIES' if anomalies else 'EXACT_ROW_SEQUENCE')
                  if same else 'ROW_SEQUENCE_MISMATCH',
        'instrument': instrument, 'provider': provider,
        'ascii': a, 'mt': b, 'compared_row_ordinals': compared,
        'equal_wall_minute_and_ohlc_rows': equal,
        'timestamp_mismatches': timestamp_mismatch,
        'ohlc_mismatches_at_same_minute': price_mismatch,
        'sampled_mismatches': samples,
        'comparison': 'Original row order, naive wall minute and exact decimal BID OHLC; volume not compared',
        'source_clock_verified': False, 'source_authenticity_verified': False,
        'usage_rights_verified': False, 'market_calendar_verified': False,
        'executable_bid_ask_verified': False, 'research_ready': False,
        'can_auto_import': False, 'live': False, 'may_execute_order': False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('ascii_zip')
    parser.add_argument('mt_zip')
    parser.add_argument('--instrument', required=True)
    parser.add_argument('--provider', required=True)
    args = parser.parse_args(argv)
    try:
        result = compare_duplicate_archives(args.ascii_zip, args.mt_zip,
                                            instrument=args.instrument, provider=args.provider)
    except (ParityInputError, OSError, ValueError, UnicodeError, csv.Error,
            zipfile.BadZipFile, RuntimeError):
        print(json.dumps({'result': 'REJECTED', 'research_ready': False,
                          'can_auto_import': False, 'live': False, 'may_execute_order': False}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
