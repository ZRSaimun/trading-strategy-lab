# One-shot Twelve Data M1 observation (DISCONNECTED; not live)

`app.prospective_twelvedata_receipt.review_twelvedata_completed_m1` is an
**explicitly invoked**, read-only bridge between the existing authenticated
Twelve Data historical `/time_series` client and the offline expected-bar
manifest / prospective receipt census. No route, scheduler, background polling,
secret storage, subscription, database write or trade execution is introduced.
**Do not invoke against a real account until the owner confirms endpoint
entitlement, credit consumption, retention, display and non-display rights.**

The only permitted mapping is `XAUUSD-TD` -> `XAU/USD`; identity is fixed as
`provider=twelvedata`, `venue=UNVERIFIED`, `price_side=UNSPECIFIED`. No
BID/ASK, CFD broker quote, spread, or market venue is inferred. The adapter
requires an immutable operator-declared UTC expected-bar manifest and validates
it **before** any network request. It requests at most 5,000 bars, with the
last expected bar as the request end. It uses the existing fixed HTTPS endpoint,
API-key header, bounded response and normalized source snapshot checks. After
response, the backend stamps **every received row with the same actual response
receipt time**; it never trusts caller-provided timestamps. This timestamp is
not a provider-signed exchange clock and does not mean each bar was freshly
formed. The existing census flags late, stale, missing, unexpected, duplicate
and conflicting rows; it does not fill gaps or modify prices.

Outputs contain source-snapshot SHA-256, server request/receipt timestamps,
request elapsed time, the operator manifest hash, and a server-observed manifest
hash. They **always** say `source_authenticated=false`,
`provider_entitlement_verified=false`, `expected_calendar_verified=false`,
`executable_bid_ask_verified=false`, `live=false`, `may_execute_order=false`.
The fixed TLS endpoint and successful API-key request do not establish source
signature, venue, calendar truth, legal data rights, or live feed latency.

## Synthetic verification

`cd backend && PYTHONPATH=. pytest -q tests/test_prospective_twelvedata_receipt.py`

Tests replace the network request and server clock. No API key or provider
credits are consumed. This is **not** a staging acceptance test against real
licensed data. In particular, a provider returning only recent N bars can
miss earlier expected bars; the census must report the missing population.

## Activation prerequisites

1. Verify instrument-specific Twelve Data M1 entitlement, permitted polling
   frequency and credit consumption; do not silently enable polling.
2. Obtain independently versioned venue/session/DST/holiday and exceptional
   closure evidence for the exact symbol; operator declarations are not proof.
3. Confirm price-side and aggregation semantics with the vendor, plus rights
   for storage, display, non-display, derived data and redistribution.
4. Integrate an owner-authenticated, least-privilege server-side invocation
   path and protected secrets, durable append-only receipts, provider-side
   correction/replay reconciliation, and independently validated UTC clocks.
5. Pass exact-head CI, private staging and production restore/rollback/health
   drills before any deployment. Never represent this module as a live feed.

Official API reference: https://twelvedata.com/docs (`/time_series`, `1min`,
`timezone=UTC`, per-symbol credit cost). Trading 212's official API is
Invest/Stocks ISA only, not a CFD market-data substitute:
https://docs.trading212.com/api.
