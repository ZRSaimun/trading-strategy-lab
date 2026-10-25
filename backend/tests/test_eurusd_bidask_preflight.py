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

    def test_python_float_permissive_numeric_lexemes_are_rejected(self):
        # float() accepts underscores and non-ASCII digits. Neither belongs
        # in an authenticated-looking price/volume export.
        for field, replacement in (
            ('open', '1.2_0000'),
            ('open', '１.２００００'),
            ('open', '1_20000e-5'),
            ('volume', '０'),
        ):
            for interval in ('M1', 'H1'):
                for side in ('bid', 'ask'):
                    with self.subTest(field=field, replacement=replacement,
                                      interval=interval, side=side):
                        original = BID if side == 'bid' else ASK
                        if field == 'open':
                            original = original.replace(
                                '1.20000' if side == 'bid' else '1.20012',
                                replacement)
                        else:
                            original = original.replace(',0\\n', f',{replacement}\\n')
                        bid = original if side == 'bid' else BID
                        ask = original if side == 'ask' else ASK
                        with self.assertRaisesRegex(ValueError, 'invalid numeric field'):
                            self.check(bid, ask, interval=interval)

    def test_ascii_scientific_notation_remains_supported(self):
        bid = BID.replace('1.20000', '1.20000e0').replace(',0\n', ',0e0\n')
        ask = ASK.replace('1.20012', '1.20012E+0').replace(',0\n', ',0e0\n')
        for interval in ('M1', 'H1'):
            with self.subTest(interval=interval):
                report = self.check(bid, ask, interval=interval)
                self.assertEqual(report['rows'], 1)
                self.assertFalse(report['approved_for_backtest'])

    def test_nan_volume_rejected(self):
        with self.assertRaisesRegex(ValueError, 'invalid numeric field'):
            self.check(BID.replace(',0\n', ',nan\n'), ASK)

    def test_observed_gap_not_forward_filled(self):
        report = self.check(BID+BID.replace('00:00:00', '00:03:00'),
                            ASK+ASK.replace('00:00:00', '00:03:00'))
        self.assertEqual(report['observed_gaps_over_interval'], 1)
        self.assertEqual(report['observed_unrepresented_interval_slots'], 2)
        self.assertEqual(report['largest_observed_gap_seconds'], 180)
        self.assertEqual(report['observed_gap_samples_first_10'], [{
            'previous_observed_utc': '2021-01-04T00:00:00+00:00',
            'next_observed_utc': '2021-01-04T00:03:00+00:00',
            'unrepresented_interval_slots': 2,
        }])
        self.assertFalse(report['observed_gap_samples_truncated'])
        self.assertEqual(report['rows'], 2)

    def test_non_minute_rejected(self):
        with self.assertRaisesRegex(ValueError, 'non-minute'):
            self.check(BID.replace('00:00:00', '00:00:30'), ASK)

    def test_wrong_header_rejected(self):
        with self.assertRaisesRegex(ValueError, 'header'):
            inspect_eurusd_pair((HEADER.replace('Etc/UTC','Local')+BID).encode(),
                                (HEADER+ASK).encode(), interval='M1')

    def test_close_spread_percentiles_use_observed_closes_not_intrabar_extrema(self):
        # Five causal, same-time synthetic closes: 1, 2, 3, 4 and 5 pips.
        # The ASK high is intentionally far above every close; OHLC high/low
        # spreads cannot be treated as simultaneous executable quotes.
        ask = ''.join(
            ASK.replace('00:00:00', f'00:0{i}:00')
               .replace('1.20032', '1.20150')
               .replace('1.20022', f'{1.20010 + i * 0.00010:.5f}')
            for i in range(1, 6)
        )
        # The timestamps must match; separate spread magnitudes from bar index.
        bid = ''.join(BID.replace('00:00:00', f'00:0{i}:00') for i in range(1, 6))
        report = self.check(bid, ask)
        self.assertEqual(report['observed_close_spread_sample_count'], 5)
        self.assertEqual(report['observed_close_spread_p50_pips'], 3.0)
        self.assertEqual(report['observed_close_spread_p95_pips'], 5.0)
        self.assertFalse(report['broker_executable_quotes'])
        self.assertFalse(report['approved_for_backtest'])

    def test_single_close_spread_is_not_invented_into_a_distribution(self):
        report = self.check()
        self.assertEqual(report['observed_close_spread_sample_count'], 1)
        self.assertEqual(report['observed_close_spread_p50_pips'], 1.2)
        self.assertEqual(report['observed_close_spread_p95_pips'], 1.2)

    def test_hourly_pair_uses_hourly_cadence(self):
        bid = BID + BID.replace('00:00:00', '01:00:00')
        ask = ASK + ASK.replace('00:00:00', '01:00:00')
        report = self.check(bid, ask, interval='H1')
        self.assertEqual(report['interval'], 'H1')
        self.assertEqual(report['interval_seconds'], 3600)
        self.assertEqual(report['observed_gaps_over_interval'], 0)
        self.assertEqual(report['observed_unrepresented_interval_slots'], 0)
        self.assertEqual(report['largest_observed_gap_seconds'], 0)
        self.assertEqual(report['observed_gap_samples_first_10'], [])
        self.assertFalse(report['observed_gap_samples_truncated'])
        self.assertFalse(report['approved_for_backtest'])

    def test_hourly_weekend_gap_is_observed_not_filled(self):
        bid = BID + BID.replace('2021-01-04T00:00:00', '2021-01-06T01:00:00')
        ask = ASK + ASK.replace('2021-01-04T00:00:00', '2021-01-06T01:00:00')
        report = self.check(bid, ask, interval='H1')
        self.assertEqual(report['rows'], 2)
        self.assertEqual(report['observed_gaps_over_interval'], 1)
        self.assertEqual(report['observed_unrepresented_interval_slots'], 48)
        self.assertEqual(report['largest_observed_gap_seconds'], 49 * 3600)
        self.assertEqual(report['observed_gap_samples_first_10'][0]['unrepresented_interval_slots'], 48)
        self.assertFalse(report['observed_gap_samples_truncated'])
        self.assertFalse(report['approved_for_backtest'])

    def test_multiple_gaps_report_slots_without_inventing_market_activity(self):
        bid = BID + BID.replace('00:00:00', '00:03:00') + BID.replace('00:00:00', '00:08:00')
        ask = ASK + ASK.replace('00:00:00', '00:03:00') + ASK.replace('00:00:00', '00:08:00')
        report = self.check(bid, ask)
        self.assertEqual(report['rows'], 3)
        self.assertEqual(report['observed_gaps_over_interval'], 2)
        self.assertEqual(report['observed_unrepresented_interval_slots'], 6)
        self.assertEqual(report['largest_observed_gap_seconds'], 300)
        self.assertFalse(report['approved_for_backtest'])

    def test_gap_samples_bounded_without_suppressing_full_counts(self):
        # Twelve separate 3-minute jumps, each hiding two unrepresented slots.
        times = [f'00:{i * 3:02d}:00' for i in range(13)]
        bid = ''.join(BID.replace('00:00:00', time) for time in times)
        ask = ''.join(ASK.replace('00:00:00', time) for time in times)
        report = self.check(bid, ask)
        self.assertEqual(report['observed_gaps_over_interval'], 12)
        self.assertEqual(report['observed_unrepresented_interval_slots'], 24)
        self.assertEqual(len(report['observed_gap_samples_first_10']), 10)
        self.assertEqual(report['observed_gap_samples_first_10'][-1]['next_observed_utc'],
                         '2021-01-04T00:30:00+00:00')
        self.assertTrue(report['observed_gap_samples_truncated'])
        self.assertFalse(report['approved_for_backtest'])

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

    def test_negative_zero_offset_is_unknown_not_verified_utc(self):
        # RFC 3339 reserves -00:00 for an unknown offset; datetime.fromisoformat
        # normalizes it to UTC, which would silently erase that uncertainty.
        for interval in ('M1', 'H1'):
            for side in ('bid', 'ask', 'both'):
                with self.subTest(interval=interval, side=side):
                    bid = BID.replace('Z', '-00:00') if side != 'ask' else BID
                    ask = ASK.replace('Z', '-00:00') if side != 'bid' else ASK
                    with self.assertRaisesRegex(ValueError, 'unknown UTC offset'):
                        self.check(bid, ask, interval=interval)

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
