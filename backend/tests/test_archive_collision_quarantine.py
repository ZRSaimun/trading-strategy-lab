"""Synthetic ZIP fixtures; no licensed market data, network, or credentials."""
import io
from contextlib import redirect_stdout
from pathlib import Path
import tempfile
import unittest
import zipfile

from app.archive_collision_quarantine import scan_archive_collisions, main
from app.archive_duplicate_parity import ParityInputError


class CollisionQuarantineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'source.zip'

    def archive(self, rows):
        with zipfile.ZipFile(self.path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr('data.csv', '\n'.join(rows) + '\n')
            z.writestr('vendor.txt', 'unverified gap report')
        return self.path

    def scan(self, rows, **kw):
        self.archive(rows)
        return scan_archive_collisions(self.path, data_format='ascii', instrument='XAUUSD',
                                       provider='HistData', **kw)

    def test_nonadjacent_conflicting_repeat_is_detected(self):
        r = self.scan(['20261016 120000;100;101;99;100;0',
                       '20261016 120100;100;102;99;101;0',
                       '20261016 120000;100;103;99;102;0'])
        self.assertEqual(r['repeated_rows'], 1)
        self.assertEqual(r['collision_minutes'], 1)
        self.assertEqual(r['conflicting_collision_minutes'], 1)
        self.assertEqual(r['adjacent_duplicate_minutes'], 0)
        self.assertEqual(r['backward_jumps'], 1)
        self.assertEqual(r['sampled_collision_locations'][0]['first_row_ordinal'], 1)
        self.assertEqual(r['sampled_collision_locations'][0]['repeated_row_ordinal'], 3)
        self.assertEqual(r['result'], 'QUARANTINE_REQUIRED')
        self.assertFalse(r['can_auto_import'])
        self.assertNotIn('100', str(r['sampled_collision_locations']))

    def test_repeat_with_same_price_then_conflict(self):
        a = '20261016 120000;100;101;99;100;0'
        b = '20261016 120100;100;102;99;101;0'
        c = '20261016 120000;100;104;99;102;0'
        r = self.scan([a, b, a, a, c])
        self.assertEqual(r['repeated_rows'], 3)
        self.assertEqual(r['collision_minutes'], 1)
        self.assertEqual(r['conflicting_repeated_rows_vs_first'], 1)
        self.assertEqual(r['conflicting_collision_minutes'], 1)

    def test_clean_never_auto_approved(self):
        r = self.scan(['20261016 120000;100;101;99;100;0',
                       '20261016 120100;100;102;99;101;0'])
        self.assertEqual(r['result'], 'FORMAT_CHECK_ONLY_UNVERIFIED')
        self.assertFalse(r['research_ready'])
        self.assertFalse(r['live'])

    def test_unique_budget_fails_closed(self):
        rows = ['20261016 120000;100;101;99;100;0',
                '20261016 120100;100;102;99;101;0']
        with self.assertRaises(ParityInputError):
            self.scan(rows, max_unique_minutes=1)

    def test_invalid_row_fails_closed(self):
        with self.assertRaises(ParityInputError):
            self.scan(['bad'])

    def test_cli_failure_sanitized(self):
        self.archive(['bad'])
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([str(self.path), '--format', 'ascii', '--instrument', 'XAUUSD',
                         '--provider', 'HistData'])
        self.assertEqual(code, 2)
        self.assertIn('REJECTED', out.getvalue())
        self.assertNotIn('bad', out.getvalue())

    def test_bounded_samples(self):
        a = '20261016 120000;100;101;99;100;0'
        b = '20261016 120100;100;102;99;101;0'
        r = self.scan([a, b, a, a, a], sample_limit=1)
        self.assertEqual(r['repeated_rows'], 3)
        self.assertEqual(len(r['sampled_collision_locations']), 1)

    def test_mt_supported(self):
        self.archive(['2026.10.16,12:00,100,101,99,100,0',
                      '2026.10.16,12:01,100,102,99,101,0',
                      '2026.10.16,12:00,100,103,99,102,0'])
        r = scan_archive_collisions(self.path, data_format='mt', instrument='XAUUSD', provider='HistData')
        self.assertEqual(r['conflicting_collision_minutes'], 1)


    def test_day_counts_reconcile_distinct_minutes(self):
        a = '20261001 120000;100;101;99;100;0'
        b = '20261001 120100;100;101;99;100;0'
        c = '20261001 120000;100;102;99;101;0'
        d = '20261002 120000;100;101;99;100;0'
        e = '20261002 120100;100;101;99;100;0'
        r = self.scan([a, b, a, c, d, e, d])
        self.assertEqual(r['first_collision_row_ordinal'], 3)
        self.assertEqual(r['last_collision_row_ordinal'], 7)
        self.assertEqual(r['collision_counts_by_unverified_wall_day'], [
            {'wall_day_unverified': '2026-10-01', 'repeated_rows': 2,
             'conflicting_repeated_rows': 1, 'distinct_collision_minutes': 1,
             'distinct_conflicting_minutes': 1},
            {'wall_day_unverified': '2026-10-02', 'repeated_rows': 1,
             'conflicting_repeated_rows': 0, 'distinct_collision_minutes': 1,
             'distinct_conflicting_minutes': 0},
        ])
        self.assertEqual(sum(d['repeated_rows'] for d in
                             r['collision_counts_by_unverified_wall_day']), r['repeated_rows'])
        self.assertEqual(sum(d['distinct_conflicting_minutes'] for d in
                             r['collision_counts_by_unverified_wall_day']),
                         r['conflicting_collision_minutes'])

    def test_clean_archive_has_no_collision_days(self):
        r = self.scan(['20261001 120000;100;101;99;100;0'])
        self.assertEqual(r['collision_counts_by_unverified_wall_day'], [])
        self.assertIsNone(r['first_collision_row_ordinal'])
        self.assertIsNone(r['last_collision_row_ordinal'])



if __name__ == '__main__':
    unittest.main()
