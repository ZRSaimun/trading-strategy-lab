# Prospective receipt freshness: expected bars versus recent traffic

The offline `audit_declared_m1_receipts` helper now treats **three different clocks**
independently. A newly received old candle is not a fresh market candle, and an
unexpected fresh receipt cannot refresh the expected population.

* `stale_declared_observation` checks the age of the newest receipt of **any**
  declared minute (existing compatibility field).
* `stale_expected_receipts` checks the age of the newest receipt whose minute is
  in the explicit expected UTC-minute population; unexpected rows cannot mask
  staleness. `seconds_since_last_expected_receipt` is null when none exists.
* `stale_expected_candle` checks `observed_at_utc - (latest_expected_minute + 60)`
  against `max_expected_close_age_seconds` (default 180). This detects replay of
  old bars even when they arrive just now. The observed age is reported as
  `seconds_since_latest_expected_close`.

Any failing freshness check yields `REVIEW_REQUIRED`, including when the caller
sets a generous receipt-lag threshold. The nonnegative integer close-age
threshold participates in the SHA-256 input fingerprint; booleans, floats and
negative thresholds are rejected. Existing gap, duplicate, price-side and
identity checks remain unchanged. No missing candles, quotes or spreads are
synthesized. Existing output keys are preserved; new keys are additive.

**Limitations:** The caller still declares receipt timestamps, expected minutes,
provider, venue and symbol. The calendar has not been independently checked for
session coverage or holidays. This module does not authenticate any provider,
verify licenses, read a broker account, establish server clock attestation,
prove real-time delivery or authorize an order. The "clean" status remains
`INTERNAL_CENSUS_ONLY_NOT_LIVE` with `live=false` and `may_execute_order=false`.

Run both test suites:

```sh
cd backend && PYTHONPATH=. pytest -q \
  tests/test_prospective_receipt_census.py \
  tests/test_prospective_receipt_freshness.py
```

For future production use, obtain an entitled authenticated source, pin its
instrument/venue/side mapping, stamp receipts at the trusted server, maintain a
separate versioned session calendar, validate the full expected bar population,
and independently test retention rights and recovery. Do not enable a feed or
merge this draft PR until the remaining release gates are satisfied.
