# Owner-invoked Trading 212 DEMO metadata staging probe (disabled)

`app.trading212_demo_staging_probe.probe_trading212_demo_metadata` is an
**opt-in, disconnected** helper for one owner-approved, **budgeted**, authenticated
**GET** of `instruments` or `exchanges` metadata in Trading 212's **DEMO**
environment. It uses the existing read-only adapter and durable per-account
request ledger. It has no route, scheduler, startup hook, persistent response
store, or live-order capability. It has **not** been run with an actual broker
account or API key.

Official API checked 26 October 2026:
https://docs.trading212.com/api . The documented API supports **Invest and
Stocks ISA**, not **CFD** accounts. Metadata is not a price feed.

## Explicit owner-only staging procedure

1. Independently verify account type, read-only key scope, API terms, instrument
   rights, key revocation procedure, and durable private ledger permissions.
2. Provision today's immutable budget with
   `app.trading212_request_budget.provision_trading212_read_budget` using the
   same verified account-scope fingerprint as all keys for that account.
3. From a private staging process only, call `probe_trading212_demo_metadata`
   with `owner_confirmed=True`, `endpoint="instruments"` or `"exchanges"`,
   `account_type="INVEST"` or `"STOCKS_ISA"`, and fresh random 128-bit
   lowercase-hex `request_id`. Pass key and secret through a private runtime
   secret manager, **never** through a public API route or source control.
4. Review the returned **redacted** evidence: local unverified receipt time,
   SHA-256 of response bytes, SHA-256 of the request ID, item count and
   observed broker quota-header status. It deliberately omits instrument
   names, tickers, response JSON, account scope, keys and secrets.
5. Reconcile quota observations with the broker account using independently
   authorized evidence. A missing/partial/inconsistent header or empty
   collection yields `REVIEW_REQUIRED`. Even `DEMO_METADATA_OBSERVED_UNVERIFIED`
   does **not** prove entitlement, licensing, freshness, broker clock, or
   identity. No result authorizes an additional API request or any order.

A failed broker GET still consumes the ledger reservation. There is no retry,
quota refund, live-environment support, CFD API access or automatic activation.
The helper cannot establish Gold/oil/Nasdaq CFD candles, executable spreads or
trading-session calendars. The owner must separately authorize and test a
licensed authenticated completed-candle provider before enabling live analysis.

Run mock-only tests with:
`cd backend && PYTHONPATH=. pytest -q tests/test_trading212_demo_staging_probe.py`.

**Release gate:** Keep PR #65 draft and undeployed until full exact-head CI,
independent licensing/entitlement checks, owner-authenticated staging, durable
backup restore, rollback rehearsal and production health checks.
