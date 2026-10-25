"""Synthetic ZIP integrity tests; never contain or import vendor prices."""
import hashlib
import io
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from app.archive_collision_quarantine import scan_archive_collisions, main
from app.archive_duplicate_parity import ParityInputError


class ArchiveFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'sample.zip'
        with zipfile.ZipFile(self.path, 'w') as z:
            z.writestr('sample.csv', '20261016 120000;100;101;99;100;0\n')
        self.digest = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def scan(self, **kwargs):
        return scan_archive_collisions(self.path, data_format='ascii',
                                       instrument='XAUUSD', provider='HistData', **kwargs)

    def test_fingerprint_and_expected_identity(self):
        report = self.scan(expected_sha256=self.digest)
        self.assertEqual(report['archive_sha256'], self.digest)
        self.assertEqual(report['archive_size_bytes'], self.path.stat().st_size)
        self.assertEqual(report['archive_integrity'], 'MATCHED_BEFORE_AND_AFTER_SCAN')
        self.assertFalse(report['can_auto_import'])

    def test_wrong_identity_rejected(self):
        with self.assertRaises(ParityInputError):
            self.scan(expected_sha256='0' * 64)

    def test_invalid_identity_rejected(self):
        for digest in ('A' * 64, '0' * 63, 'not-a-hash', 0, ''):
            with self.subTest(digest=digest), self.assertRaises(ParityInputError):
                self.scan(expected_sha256=digest)

    def test_compressed_byte_budget_rejected(self):
        with self.assertRaises(ParityInputError):
            self.scan(max_archive_bytes=self.path.stat().st_size - 1)
        with self.assertRaises(ParityInputError):
            self.scan(max_archive_bytes=True)

    def test_change_between_hash_passes_rejected(self):
        from app import archive_collision_quarantine as module
        real = module._archive_fingerprint
        n = 0

        def fake(*args, **kwargs):
            nonlocal n
            n += 1
            size, digest = real(*args, **kwargs)
            return size, digest if n == 1 else '1' * 64

        with patch.object(module, '_archive_fingerprint', side_effect=fake):
            with self.assertRaises(ParityInputError):
                self.scan()
        self.assertEqual(n, 2)

    def test_cli_rejects_bad_identity_without_path_leak(self):
        out = io.StringIO()
        with redirect_stdout(out):
            code = main([str(self.path), '--format', 'ascii',
                         '--instrument', 'XAUUSD', '--provider', 'HistData',
                         '--expected-sha256', '0' * 64])
        self.assertEqual(code, 2)
        self.assertEqual(out.getvalue().strip(),
                         '{"result": "REJECTED", "research_ready": false, "can_auto_import": false, "live": false, "may_execute_order": false}')
        self.assertNotIn(str(self.path), out.getvalue())


if __name__ == '__main__':
    unittest.main()
