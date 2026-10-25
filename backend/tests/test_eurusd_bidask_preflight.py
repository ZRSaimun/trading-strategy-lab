"""Synthetic regression fixtures; never market-history or profitability evidence."""
import unittest
from app.eurusd_bidask_preflight import inspect_eurusd_pair

HEADER = 'Etc/UTC,Open,High,Low,Close,Volume\n'
BID = '2021-01-04T00:00:00Z,1.20000,1.20020,1.19990,1.20010,0\n'
ASK = '2021-01-04T00:00:00Z,1.20012,1.20032,1.20002,1.20022,0\n'


class PairedM1PreflightTests(unittest.TestCase):
    def check(self, bid=BID, ask=ASK, interval='M1'):
        return inspect_eurusd_pair((HEADER+bid).encode(), (HEADER+ask).encode(), interval=interval)

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
        self.assertEqual(report['observed_gaps_over_interval'], 1)
        self.assertEqual(report['rows'], 2)

    def test_non_minute_rejected(self):
        with self.assertRaisesRegex(ValueError, 'non-minute'):
            self.check(BID.replace('00:00:00', '00:00:30'), ASK)

    def test_wrong_header_rejected(self):
        with self.assertRaisesRegex(ValueError, 'header'):
            inspect_eurusd_pair((HEADER.replace('Etc/UTC','Local')+BID).encode(),
                                (HEADER+ASK).encode(), interval='M1')

    def test_hourly_pair_uses_hourly_cadence(self):
        bid = BID + BID.replace('00:00:00', '01:00:00')
        ask = ASK + ASK.replace('00:00:00', '01:00:00')
        report = self.check(bid, ask, interval='H1')
        self.assertEqual(report['interval'], 'H1')
        self.assertEqual(report['interval_seconds'], 3600)
        self.assertEqual(report['observed_gaps_over_interval'], 0)
        self.assertFalse(report['approved_for_backtest'])

    def test_hourly_weekend_gap_is_observed_not_filled(self):
        bid = BID + BID.replace('2021-01-04T00:00:00', '2021-01-06T01:00:00')
        ask = ASK + ASK.replace('2021-01-04T00:00:00', '2021-01-06T01:00:00')
        report = self.check(bid, ask, interval='H1')
        self.assertEqual(report['rows'], 2)
        self.assertEqual(report['observed_gaps_over_interval'], 1)

    def test_hourly_half_hour_candle_rejected(self):
        with self.assertRaisesRegex(ValueError, 'not aligned'):
            self.check(BID.replace('00:00:00', '00:30:00'),
                       ASK.replace('00:00:00', '00:30:00'), interval='H1')

    def test_interval_must_be_explicit(self):
        with self.assertRaises(TypeError):
            inspect_eurusd_pair((HEADER+BID).encode(), (HEADER+ASK).encode())
        with self.assertRaisesRegex(ValueError, 'Explicit interval'):
            self.check(interval='4H')
        with self.assertRaisesRegex(ValueError, 'Explicit interval'):
            self.check(interval=None)

    def test_incomplete_or_alternative_timestamp_cannot_invent_midnight(self):
        for timestamp in ('2021-01-04', '20210104', '2021-W01-1',
                          '2021-01-04T00', '2021-01-04T00:00',
                          '2021-01-04X00:00:00', '2021-W01-1T00:00:00'):
            for side in ('bid', 'ask', 'both'):
                with self.subTest(timestamp=timestamp, side=side):
                    bid = BID.replace('2021-01-04T00:00:00Z', timestamp) if side != 'ask' else BID
                    ask = ASK.replace('2021-01-04T00:00:00Z', timestamp) if side != 'bid' else ASK
                    with self.assertRaisesRegex(ValueError, 'full calendar timestamp'):
                        self.check(bid, ask)

    def test_submicrosecond_precision_cannot_be_truncated_into_alignment(self):
        with self.assertRaisesRegex(ValueError, 'full calendar timestamp'):
            self.check(BID.replace('00:00:00Z', '00:00:00.0000001Z'), ASK)

    def test_complete_timestamp_formats_retain_utc_semantics(self):
        for timestamp in ('2021-01-04T00:00:00Z', '2021-01-04 00:00:00',
                          '2021-01-04T00:00:00+00:00',
                          '2021-01-04 00:00:00.000',
                          '2021-01-04T00:00:00.000000Z'):
            for interval in ('M1', 'H1'):
                with self.subTest(timestamp=timestamp, interval=interval):
                    report = self.check(
                        BID.replace('2021-01-04T00:00:00Z', timestamp),
                        ASK.replace('2021-01-04T00:00:00Z', timestamp), interval)
                    self.assertEqual(report['first_utc'], '2021-01-04T00:00:00+00:00')
                    self.assertFalse(report['approved_for_backtest'])

    def test_valid_syntax_still_requires_real_date_and_aligned_time(self):
        for timestamp in ('2021-02-30T00:00:00Z', '2021-01-04T24:00:00Z',
                          '2021-01-04T00:00:00.000001Z'):
            with self.subTest(timestamp=timestamp), self.assertRaises(ValueError):
                self.check(BID.replace('2021-01-04T00:00:00Z', timestamp), ASK)


if __name__ == '__main__':
    unittest.main()
