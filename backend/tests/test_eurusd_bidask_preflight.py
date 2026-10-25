"""Synthetic regression fixtures; never market-history or profitability evidence."""
import unittest
from app.eurusd_bidask_preflight import inspect_eurusd_pair

HEADER = 'Etc/UTC,Open,High,Low,Close,Volume\n'
BID = '2021-01-04T00:00:00Z,1.20000,1.20020,1.19990,1.20010,0\n'
ASK = '2021-01-04T00:00:00Z,1.20012,1.20032,1.20002,1.20022,0\n'


class PairedM1PreflightTests(unittest.TestCase):
    def check(self, bid=BID, ask=ASK):
        return inspect_eurusd_pair((HEADER+bid).encode(), (HEADER+ask).encode())

    def test_valid_synthetic_pair_does_not_authorize_research(self):
        report = self.check()
        self.assertEqual(report['rows'], 1)
        self.assertEqual(report['observed_open_close_spread_max_pips'], 1.2)
        self.assertFalse(report['approved_for_backtest'])
        self.assertFalse(report['broker_executable_quotes'])
        self.assertFalse(report['licensed_use_verified'])
        self.assertFalse(report['profitable_pattern_proven'])

    def test_header_only_pair_rejected(self):
        with self.assertRaisesRegex(ValueError, 'zero candles'):
            self.check('', '')

    def test_header_only_single_side_rejected(self):
        with self.assertRaisesRegex(ValueError, 'zero candles'):
            self.check(BID, '')

    def test_timestamp_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError, 'timestamp mismatch'):
            self.check(BID, ASK.replace('00:00:00', '00:01:00'))

    def test_crossed_quote_rejected(self):
        with self.assertRaisesRegex(ValueError, 'crossed'):
            self.check(BID.replace('1.20000', '1.20015'), ASK)

    def test_duplicate_rejected(self):
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            self.check(BID+BID, ASK+ASK)

    def test_backward_rejected(self):
        with self.assertRaisesRegex(ValueError, 'backward'):
            self.check(BID.replace('00:00:00', '00:01:00')+BID,
                       ASK.replace('00:00:00', '00:01:00')+ASK)

    def test_non_utc_rejected(self):
        with self.assertRaisesRegex(ValueError, 'non-UTC'):
            self.check(BID.replace('Z', '+01:00'), ASK)

    def test_invalid_ohlc_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid OHLC'):
            self.check(BID.replace('1.20020', '1.19900'), ASK)

    def test_nan_volume_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid OHLC'):
            self.check(BID.replace(',0\n', ',nan\n'), ASK)

    def test_observed_gap_not_forward_filled(self):
        report = self.check(BID+BID.replace('00:00:00', '00:03:00'),
                            ASK+ASK.replace('00:00:00', '00:03:00'))
        self.assertEqual(report['observed_gaps_over_one_minute'], 1)
        self.assertEqual(report['rows'], 2)

    def test_non_minute_rejected(self):
        with self.assertRaisesRegex(ValueError, 'non-minute'):
            self.check(BID.replace('00:00:00', '00:00:30'), ASK)

    def test_wrong_header_rejected(self):
        with self.assertRaisesRegex(ValueError, 'header'):
            inspect_eurusd_pair((HEADER.replace('Etc/UTC','Local')+BID).encode(),
                                (HEADER+ASK).encode())


if __name__ == '__main__':
    unittest.main()
