"""Read-only source-preserving audit of historical minute-bar research tables.

This is an offline data integrity report, NOT proof of source authenticity,
market coverage, executable prices or strategy profitability. Intended for
Gemini/independent model-review handoffs and baseline experiment provenance.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import sqlite3


def year_utc(timestamp: int) -> int:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).year


def scan_database(path: str) -> dict:
    """Stream data with bounded memory and detect collisions in same-source series.

    Provider/instrument/format/fixed-UTC-offset groups are distinct histories; each
    imported ZIP is its own dataset and cross-provider bars are never merged.
    """
    database = Path(path).resolve(strict=True)
    with database.open('rb') as f:
        if f.read(16) != b'SQLite format 3\x00':
            raise ValueError('Expected SQLite research database')
    con = sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True)
    try:
        con.execute('PRAGMA query_only=1')
        ds = [dict(zip([x[0] for x in q.description], row)) for q in [con.execute(
            "SELECT id,provider,instrument,format,state,archive_sha256,accepted,rejected,zero_volume,"
            "archive_filename,utc_offset_minutes FROM historical_datasets ORDER BY instrument,provider,format,id")]
            for row in q]
        badstates = [d['id'] for d in ds if d['state'] != 'READY']
        # Reconcile every READY archive separately: aggregate group totals can
        # hide one missing dataset row cancelled by an extra row in another.
        ready_row_counts = Counter()
        stats = defaultdict(lambda: {'datasets': 0, 'ready_datasets': 0, 'nonready_datasets': 0,
                  'raw_rows': 0, 'unique_minutes': 0,
                  'overlapping_minutes': 0, 'exact_overlap_rows': 0, 'conflicting_overlap_rows': 0,
                  'invalid_ohlc_rows': 0, 'zero_volume_rows': 0, 'time_gaps_gt_1m': 0,
                  'max_observed_gap_minutes': 0, 'start_utc': None, 'end_utc': None,
                  'years': defaultdict(lambda: {'unique_minutes': 0}),
                  'gap_categories_minutes': Counter()})
        for d in ds:
            k = (d['provider'], d['instrument'], d['format'], d['utc_offset_minutes'])
            stats[k]['datasets'] += 1
            stats[k]['ready_datasets' if d['state'] == 'READY' else 'nonready_datasets'] += 1
        sql = '''SELECT d.provider,d.instrument,d.format,d.utc_offset_minutes,
                        c.time,c.open,c.high,c.low,c.close,c.volume,c.dataset_id
                 FROM historical_candles c JOIN historical_datasets d ON d.id = c.dataset_id
                 WHERE d.state = 'READY'
                 ORDER BY d.provider,d.instrument,d.format,d.utc_offset_minutes,c.time,c.dataset_id'''
        previous_key = previous_t = previous_values = None
        for provider, instrument, fmt, offset, t, o, h, l, c, v, dsid in con.execute(sql):
            k = (provider, instrument, fmt, offset)
            ready_row_counts[dsid] += 1
            s = stats[k]
            s['raw_rows'] += 1
            s['zero_volume_rows'] += int(v == 0)
            if not all(math.isfinite(x) for x in (o, h, l, c)) or l > min(o,c) or h < max(o,c) or l > h:
                s['invalid_ohlc_rows'] += 1
            if previous_key == k and previous_t == t:
                s['overlapping_minutes'] += 1
                if (o,h,l,c) == previous_values:
                    s['exact_overlap_rows'] += 1
                else:
                    s['conflicting_overlap_rows'] += 1
                continue
            if previous_key == k and previous_t is not None:
                dt = t - previous_t
                if dt > 60:
                    s['time_gaps_gt_1m'] += 1
                    gap_minutes = dt // 60 - 1
                    s['max_observed_gap_minutes'] = max(s['max_observed_gap_minutes'], gap_minutes)
                    cat = '2-5' if dt <= 300 else '6-59' if dt < 3600 else '60+'
                    s['gap_categories_minutes'][cat] += 1
            previous_key = k
            previous_t = t
            previous_values = (o,h,l,c)
            s['unique_minutes'] += 1
            yr = str(year_utc(t))
            s['years'][yr]['unique_minutes'] += 1
            iso = datetime.fromtimestamp(t,timezone.utc).isoformat()
            if s['start_utc'] is None:
                s['start_utc'] = iso
            s['end_utc'] = iso
        samples_by_group = {}
        for d in ds:
            k = (d['provider'], d['instrument'], d['format'], d['utc_offset_minutes'])
            samples_by_group.setdefault(k, {
                'accepted_imported': 0, 'rejected_imported': 0, 'zero_volume_imported': 0,
                'nonready_accepted_imported': 0, 'nonready_rejected_imported': 0,
            })
            x = samples_by_group[k]
            if d['state'] == 'READY':
                x['accepted_imported'] += d['accepted']
                x['rejected_imported'] += d['rejected']
                x['zero_volume_imported'] += d['zero_volume']
            else:
                # Interrupted/failed imports may have committed checkpoints.
                # Those rows are intentionally excluded from READY price scans.
                x['nonready_accepted_imported'] += d['accepted']
                x['nonready_rejected_imported'] += d['rejected']
        report = {'schema_version': 2, 'type': 'historical_minute_data_quality',
          'input': {'database_name': database.name,
                    'datasets': len(ds), 'nonready_dataset_count': len(badstates)},
          'dataset_manifest': [dict(id=d['id'], instrument=d['instrument'], provider=d['provider'],
                file_format=d['format'], filename=d['archive_filename'],
                archive_sha256=d['archive_sha256'], utc_offset_minutes=d['utc_offset_minutes'],
                accepted=d['accepted'], rejected=d['rejected'],
                zero_volume=d['zero_volume'], state=d['state'],
                observed_ready_rows=(ready_row_counts[d['id']] if d['state'] == 'READY' else None),
                accepted_count_matches=(ready_row_counts[d['id']] == d['accepted']
                                        if d['state'] == 'READY' else None)) for d in ds],
          'definitions': {
             'gap': 'Difference >60 seconds between observed M1 timestamps; may be market closure or missing data',
             'overlap': 'Extra row at same timestamp within SAME provider, instrument, file format and declared UTC offset',
             'source_identity': 'Declared fixed UTC offset is part of each audit group; different offsets are not silently compared or combined',
             'duplicate': 'Identical OHLC repeated at that timestamp, not an independent observation',
             'zero_volume': 'Provider numeric zero, not proof that no trading occurred',
             'data_limitations': 'HistData bid-only quotes; no ask side, independently verified spread, or execution volume',
             'nonready': 'Incomplete datasets excluded from price calculations and ready-row reconciliation; their checkpoint counts are reported separately',
             'ready_row_reconciliation': 'Each READY dataset observed row count is checked against its own accepted import counter; grouped totals may hide offsetting per-dataset discrepancies'},
          'groups': []}
        for k in sorted(stats):
            s = stats[k]
            group = {'provider':k[0], 'instrument':k[1], 'format':k[2],
                     'utc_offset_minutes':k[3]}
            group.update({name: value for name,value in s.items() if name not in {'years','gap_categories_minutes'}})
            group['years'] = {yr: data for yr,data in sorted(s['years'].items())}
            group['gap_categories_minutes'] = dict(s['gap_categories_minutes'])
            group.update(samples_by_group[k])
            report['groups'].append(group)
        report['summary'] = {
             'source_rows':sum(s['raw_rows'] for s in stats.values()),
             'distinct_within_source_group_minutes':sum(s['unique_minutes'] for s in stats.values()),
             'source_overlap_extra_rows':sum(s['overlapping_minutes'] for s in stats.values()),
             'overlap_conflicts':sum(s['conflicting_overlap_rows'] for s in stats.values()),
             'import_rejections':sum(d['rejected'] for d in ds),
             'invalid_ohlc_in_ready':sum(s['invalid_ohlc_rows'] for s in stats.values()),
             'ready_dataset_count_mismatch':sum(ready_row_counts[d['id']] != d['accepted']
                 for d in ds if d['state'] == 'READY'),
             'accepted_count_mismatch':sum(s['raw_rows'] != samples_by_group[k]['accepted_imported']
                 for k, s in stats.items())}
        return report
    finally:
        con.close()


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('database', type=Path, help='Existing SQLite archive database (opened read-only)')
    p.add_argument('--output', type=Path, help='Private JSON report destination')
    args = p.parse_args(argv)
    report = scan_database(str(args.database))
    payload = json.dumps(report, sort_keys=True, indent=2) + '\n'
    if args.output:
        args.output.write_text(payload)
        print(f'Saved read-only audit: {args.output} ({len(payload)} bytes)')
    else:
        print(payload)

if __name__ == '__main__':
    main()