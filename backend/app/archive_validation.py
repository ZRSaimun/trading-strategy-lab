"""Streaming, read-only HistData ASCII M1 archive validation.

No prices are repaired or imported. Caller must declare a fixed UTC offset from
verified source conventions; a local/DST timezone is deliberately not guessed.
"""
import csv
import hashlib
import io
import math
import zipfile
from datetime import datetime, timedelta, timezone


def inspect_archive(path, *, instrument, provider, utc_offset_minutes,
                    max_uncompressed_bytes=2_000_000_000, max_rows=20_000_000, data_format='ascii'):
    if data_format not in ('ascii', 'mt'):
        raise ValueError('Supported formats: ascii, mt')
    if not instrument.strip() or not provider.strip():
        raise ValueError('Exact instrument and provider identities required')
    if not isinstance(utc_offset_minutes, int) or abs(utc_offset_minutes) > 840:
        raise ValueError('Declare a verified fixed UTC offset in minutes')
    digest = hashlib.sha256()
    with open(path, 'rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    report = dict(sha256=digest.hexdigest(), instrument=instrument, provider=provider,
                  utc_offset_minutes=utc_offset_minutes, format=f'HistData {data_format.upper()} M1', price_side='bid',
                  source_authenticity='unverified; hash proves identity, not origin',
                  rows=0, valid_rows=0, quarantined_rows=0, zero_volume_rows=0,
                  gap_events=0, start=None, end=None, issues={}, samples=[], members=[])
    def issue(kind, member, line):
        report['issues'][kind] = report['issues'].get(kind, 0) + 1
        if len(report['samples']) < 100:
            report['samples'].append(dict(issue=kind, member=member, line=line))
    tz = timezone(timedelta(minutes=utc_offset_minutes))
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if len(members) > 1000 or sum(m.file_size for m in members) > max_uncompressed_bytes:
            raise ValueError('Archive exceeds bounded resource policy')
        for member in members:
            if member.is_dir():
                continue
            if not member.filename.lower().endswith('.csv'):
                issue('unsupported_member', member.filename, 0)
                continue
            report['members'].append(dict(name=member.filename, bytes=member.file_size,
                                          crc32=f'{member.CRC:08x}'))
            previous = None
            with archive.open(member) as binary:
                reader = csv.reader(io.TextIOWrapper(binary, encoding='utf-8-sig', errors='strict'), delimiter=';' if data_format == 'ascii' else ',')
                for line, row in enumerate(reader, 1):
                    report['rows'] += 1
                    if report['rows'] > max_rows:
                        raise ValueError('Archive exceeds row budget')
                    try:
                        if data_format == 'mt':
                            if len(row) != 7:
                                raise ValueError('invalid_columns')
                            parsed = datetime.strptime(row[0] + ' ' + row[1], '%Y.%m.%d %H:%M')
                            row = [parsed.strftime('%Y%m%d %H%M%S'), *row[2:]]
                        if len(row) != 6:
                            raise ValueError('invalid_columns')
                        dt = datetime.strptime(row[0], '%Y%m%d %H%M%S').replace(tzinfo=tz)
                        stamp = int(dt.timestamp())
                        if dt.second:
                            raise ValueError('not_minute_aligned')
                        o, h, l, c, v = map(float, row[1:])
                        if not all(math.isfinite(x) for x in (o, h, l, c, v)):
                            raise ValueError('nonfinite_value')
                        if l > min(o, c) or h < max(o, c) or l > h or v < 0:
                            raise ValueError('invalid_ohlcv')
                        if v == 0:
                            report['zero_volume_rows'] += 1
                        if previous is not None and stamp <= previous:
                            raise ValueError('duplicate_timestamp' if stamp == previous else 'backward_timestamp')
                        if previous is not None and stamp - previous > 60:
                            report['gap_events'] += 1
                        previous = stamp
                        report['valid_rows'] += 1
                        report['start'] = stamp if report['start'] is None else min(stamp, report['start'])
                        report['end'] = stamp if report['end'] is None else max(stamp, report['end'])
                    except ValueError as exc:
                        report['quarantined_rows'] += 1
                        kind = str(exc) if str(exc) in {'invalid_columns', 'not_minute_aligned', 'nonfinite_value', 'invalid_ohlcv', 'duplicate_timestamp', 'backward_timestamp'} else 'invalid_timestamp_or_number'
                        issue(kind, member.filename, line)
    report['limitations'] = ['Cross-member and nonadjacent collisions require database deduplication',
                            'Gaps may be market closures; no calendar supplied',
                            'Zero volume is flagged, not interpreted as traded volume',
                            'No spread, price anomaly, licensing or source authenticity verification',
                            'No records imported; quarantine contains locations only']
    return report

if __name__ == '__main__':
    import argparse
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--format', choices=['ascii', 'mt'], default='ascii')
    parser.add_argument('--instrument', required=True)
    parser.add_argument('--provider', required=True)
    parser.add_argument('--utc-offset-minutes', type=int, required=True)
    args = parser.parse_args()
    print(json.dumps(inspect_archive(args.archive, instrument=args.instrument,
                                    provider=args.provider,
                                    utc_offset_minutes=args.utc_offset_minutes, data_format=args.format), indent=2))
