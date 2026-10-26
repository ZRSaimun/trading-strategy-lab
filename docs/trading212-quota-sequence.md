# Trading 212 quota sequence review (disconnected)

`app.trading212_quota_sequence.audit_trading212_quota_sequence` reviews up to 500 **caller-supplied** response observations from the optional `fetch_trading212_readonly` GET adapter. It does not contact Trading 212, store account information, fetch prices, schedule requests, authorize another request or place an order. It never returns account payloads, response hashes, keys, credentials or header values; only bounded issue counts and explicit unverified flags.

The official [Trading 212 API documentation](https://docs.trading212.com/api/section/rate-limiting/response-headers), checked 26 October 2026, describes five rate-limit headers. `x-ratelimit-reset` is a Unix timestamp, and limits are per account across keys/IPs. This API is documented for **Invest and Stocks ISA, not CFD**. No authenticated account or entitlement has been verified.

## Checks

* Strict UTC receipt/as-of timestamps; reject invalid schema and any attempt to set authority flags to true.
* Distinguish missing/partial/inconsistent header observations from internally consistent **but unverified** ones.
* Compare `used`/`remaining` monotonically only for matching endpoint, declared environment/account type, period, limit and exact reset timestamp. Another client may consume many requests between observations; **no assumption of one credit per observation**.
* Mark reset transitions and cross-endpoint/account-scope comparisons as non-comparable. Flag reset timestamps that are stale or implausibly distant relative to a declared period, but do not treat local machine receipt time as an attested broker clock.
* Never infer independent account identity, provider signature, actual account-wide remaining quota, market-data licensing, price freshness or authorization to send another request.

A result of `CONSISTENT_UNVERIFIED` means **only** that the supplied observations passed internal checks. It is not evidence that the receipts are authentic or that the account has capacity. A result of `REVIEW_REQUIRED` means supplied observations need investigation. Neither status permits an API request, market-data activation, paper fill or real-money order.

Run offline regression tests:

```sh
cd backend && PYTHONPATH=. pytest -q tests/test_trading212_quota_sequence.py
```

Release remains blocked pending independent owner-controlled account eligibility, entitlement and retention-rights verification, securely scoped secrets, durable account-wide request reservation, authenticated staging acceptance, verified historical data provenance and session calendars, production backup restoration, rollback and post-deploy health checks. Keep PR #65 draft/unmerged/undeployed until those checks pass.
