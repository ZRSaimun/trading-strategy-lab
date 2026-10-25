"""Synthetic ZIP fixtures only; no licensed data, secrets, or network."""
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from app.archive_duplicate_parity import compare_duplicate_archives, ParityInputError, main


def archive(path, rows, fmt, member='ticks.csv'):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr(member, '\n'.join(rows) + '\n')


class DuplicateParityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.a = Path(self.temp.name) / 'ascii.zip'
        self.b = Path(self.temp.name) / 'mt.zip'
        self.a_rows = [
            '20261016 120000;100;101;99;100;0',
            '20261016 120100;100;102;99;101;0',
            '20261016 120100;101;103;100;102;0',
            '20261016 115900;100;101;99;100;0',
        ]
        self.b_rows = [
            '2026.10.16,12:00,100,101,99,100,0',
            '2026.10.16,12:01,100,102,99,101,0',
            '2026.10.16,12:01,101,103,100,102,0',
            '2026.10.16,11:59,100,101,99,100,0',
        ]

    def check(self, left=None, right=None):
        archive(self.a, self.a_rows if left is None else left, 'ascii')
        archive(self.b, self.b_rows if right is None else right, 'mt')
        return compare_duplicate_archives(self.a, self.b, instrument='XAUUSD', provider='HistData')

    def test_matching_duplicate_and_backward_are_not_approved(self):
        result = self.check()
        self.assertEqual(result['result'], 'EXACT_ROW_SEQUENCE_WITH_ANOMALIES')
        self.assertEqual(result['equal_wall_minute_and_ohlc_rows'], 4)
        self.assertEqual(result['ascii']['adjacent_duplicate_minutes'], 1)
        self.assertEqual(result['ascii']['conflicting_adjacent_duplicate_ohlc'], 1)
        self.assertEqual(result['mt']['backward_jumps'], 1)
        for field in ('source_clock_verified', 'source_authenticity_verified',
                      'usage_rights_verified', 'research_ready', 'can_auto_import',
                      'live', 'may_execute_order'):
            self.assertIs(result[field], False)

    def test_mismatch_at_repeated_minute(self):
        rows = self.b_rows.copy()
        rows[2] = '2026.10.16,12:01,101,103,100,101,0'
        result = self.check(right=rows)
        self.assertEqual(result['result'], 'ROW_SEQUENCE_MISMATCH')
        self.assertEqual(result['ohlc_mismatches_at_same_minute'], 1)
        self.assertEqual(result['sampled_mismatches'][0]['row_ordinal'], 3)

    def test_mismatch_timestamp(self):
        rows = self.b_rows.copy()
        rows[0] = '2026.10.16,12:02,100,101,99,100,0'
        result = self.check(right=rows)
        self.assertEqual(result['timestamp_mismatches'], 1)

    def test_row_count_mismatch(self):
        result = self.check(right=self.b_rows[:-1])
        self.assertEqual(result['result'], 'ROW_SEQUENCE_MISMATCH')
        self.assertEqual(result['compared_row_ordinals'], 4)

    def test_clean_matching(self):
        result = self.check(left=self.a_rows[:2], right=self.b_rows[:2])
        self.assertEqual(result['result'], 'EXACT_ROW_SEQUENCE')

    def test_bad_ohlc_rejected(self):
        rows = self.b_rows.copy()
        rows[0] = '2026.10.16,12:00,100,98,99,100,0'
        with self.assertRaises(ParityInputError):
            self.check(right=rows)

    def test_nonfinite_rejected(self):
        rows = self.b_rows.copy()
        rows[0] = '2026.10.16,12:00,NaN,101,99,100,0'
        with self.assertRaises(ParityInputError):
            self.check(right=rows)

    def test_nonminute_rejected(self):
        rows = self.a_rows.copy()
        rows[0] = '20261016 120001;100;101;99;100;0'
        with self.assertRaises(ParityInputError):
            self.check(left=rows)

    def test_nested_member_rejected(self):
        archive(self.a, self.a_rows, 'ascii', member='../ticks.csv')
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b, instrument='XAUUSD', provider='HistData')

    def test_actual_histdata_layout_csv_plus_status_txt(self):
        archive(self.a, self.a_rows, 'ascii')
        archive(self.b, self.b_rows, 'mt')
        for path in (self.a, self.b):
            with zipfile.ZipFile(path, 'a') as z:
                z.writestr('DAT_XAUUSD_M1_202610.txt',
                           'Gap of 3600s found between unverified vendor ticks.\n')
        result = compare_duplicate_archives(self.a, self.b,
                                            instrument='XAUUSD', provider='HistData')
        self.assertEqual(result['result'], 'EXACT_ROW_SEQUENCE_WITH_ANOMALIES')
        self.assertTrue(result['ascii']['vendor_status_report_present'])
        self.assertTrue(result['mt']['vendor_status_report_present'])
        self.assertIs(result['research_ready'], False)

    def test_oversized_vendor_status_txt_rejected(self):
        archive(self.a, self.a_rows, 'ascii')
        with zipfile.ZipFile(self.a, 'a') as z:
            z.writestr('status.txt', 'x' * 32769)
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b,
                                       instrument='XAUUSD', provider='HistData')

    def test_nested_vendor_status_txt_rejected(self):
        archive(self.a, self.a_rows, 'ascii')
        with zipfile.ZipFile(self.a, 'a') as z:
            z.writestr('reports/status.txt', 'untrusted')
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b,
                                       instrument='XAUUSD', provider='HistData')

    def test_txt_only_zip_rejected(self):
        with zipfile.ZipFile(self.a, 'w') as z:
            z.writestr('status.txt', 'no candle data')
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b,
                                       instrument='XAUUSD', provider='HistData')

    def test_multiple_members_rejected(self):
        archive(self.a, self.a_rows, 'ascii')
        with zipfile.ZipFile(self.a, 'a') as z:
            z.writestr('extra.csv', 'bad')
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b, instrument='XAUUSD', provider='HistData')

    def test_bounded_lines_rejected(self):
        rows = self.a_rows.copy()
        rows[0] += ';' + '9' * 1024
        with self.assertRaises(ParityInputError):
            self.check(left=rows)

    def test_megabyte_single_line_rejected(self):
        # Regression: a line-length check after "for line in stream" is
        # too late to prevent allocation of an attacker-controlled line.
        rows = self.a_rows.copy()
        rows[0] += '9' * 1_000_000
        with self.assertRaises(ParityInputError):
            self.check(left=rows)

    def test_multiline_quoted_record_rejected(self):
        # HistData is plain unquoted CSV; quoted multiline fields must not
        # accumulate an arbitrarily large logical record.
        rows = self.a_rows.copy()
        rows[0] = '"' + rows[0] + '\n' + rows[1] + '"'
        with self.assertRaises(ParityInputError):
            self.check(left=rows)

    def test_crlf_plain_records_still_supported(self):
        result = self.check(left=[r + '\r' for r in self.a_rows],
                            right=[r + '\r' for r in self.b_rows])
        self.assertEqual(result['result'], 'EXACT_ROW_SEQUENCE_WITH_ANOMALIES')

    def test_budget_rejected(self):
        archive(self.a, self.a_rows, 'ascii')
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b, instrument='XAUUSD', provider='HistData', max_rows=2)

    def test_same_path_rejected(self):
        archive(self.a, self.a_rows, 'ascii')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.a, instrument='XAUUSD', provider='HistData')

    def test_invalid_budget_rejected(self):
        archive(self.a, self.a_rows, 'ascii')
        archive(self.b, self.b_rows, 'mt')
        with self.assertRaises(ParityInputError):
            compare_duplicate_archives(self.a, self.b, instrument='XAUUSD', provider='HistData', sample_limit=True)

    def test_cli_failure_is_sanitized(self):
        archive(self.a, ['bad'], 'ascii')
        archive(self.b, self.b_rows, 'mt')
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main([str(self.a), str(self.b), '--instrument', 'XAUUSD', '--provider', 'HistData'])
        self.assertEqual(code, 2)
        self.assertIn('REJECTED', buf.getvalue())
        self.assertNotIn('bad', buf.getvalue())


if __name__ == '__main__':
    unittest.main()
