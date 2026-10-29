# Trading 212 read-only Invest/Stocks ISA adapter (disconnected by default)

The optional `app.trading212_readonly.fetch_trading212_readonly` helper performs **one**
explicit, authenticated HTTPS **GET** to a fixed official Trading 212 v0 API
endpoint when the owner supplies an eligible account's API key pair. It is
**not wired into the website**, does not run on startup or in the background,
does not store credentials or responses, and cannot submit, amend or cancel
orders. No account has been connected or tested against Trading 212.

Official API reference (checked 26 Oct 2026):
https://docs.trading212.com/api

The provider documents the API for **Invest and Stocks ISA only**, including
demo and live environments. **CFD accounts are not supported by this API**.
Its equity instrument metadata and account summary are not an authenticated
stream of completed Gold, oil, Nasdaq CFD candles or executable bid/ask quotes.

## Explicit endpoint allowlist

| Input `endpoint` | Fixed GET path | Purpose |
| --- | --- | --- |
| `instruments` | `/api/v0/equity/metadata/instruments` | Eligible equity instrument metadata |
| `exchanges` | `/api/v0/equity/metadata/exchanges` | Equity exchange metadata |
| `account_summary` | `/api/v0/equity/account/summary` | Owner-only account snapshot; private |

`environment` defaults to `DEMO`; `LIVE` must be selected explicitly.
Hosts are hard-coded to `demo.trading212.com` and `live.trading212.com`.
No caller-supplied URLs, paths, redirects, proxies, write verbs, or order
endpoints are accepted. The request uses Basic authentication over
certificate-verified HTTPS. Responses are limited to 8 MiB, must be JSON and
HTTP 200, and are not automatically retried.
The JSON wire body must decode as **strict UTF-8 without a byte-order mark**.
Python's default `json.loads(bytes)` can silently accept UTF-16/UTF-32 or a
UTF-8 BOM; this adapter now rejects those encodings and invalid UTF-8 with a
sanitized `Invalid broker JSON` error. Valid non-ASCII UTF-8 remains supported.

The JSON parser also rejects isolated UTF-16 surrogate escapes in nested
string values or object keys. Python can otherwise accept such invalid Unicode
scalar values from otherwise valid UTF-8 JSON and later fail to serialize them
safely for audit or storage. Valid paired surrogate escapes and literal UTF-8
supplementary characters remain supported. All failures are sanitized, and
this check makes no additional provider requests or freshness claims.
This is format integrity only, not broker authentication, price freshness or
market-data entitlement; no network calls or write capabilities are added.
When a `Content-Length` header is supplied, the adapter now verifies that
its declared byte count exactly matches the bounded identity-encoded body
actually hashed and parsed. Mismatches fail closed with a sanitized error,
even if the received fragment is otherwise valid JSON. A missing header does
not constitute an attested length; matching lengths are transport consistency
only, **not** broker signing, vendor entitlement, or market-data authenticity. Non-200, malformed, redirected,
oversized and transport-failed responses raise a sanitized exception; their
bodies, keys and secrets are not included in error messages.

`account_type` must be explicitly declared `INVEST` or `STOCKS_ISA`.
This is **not independent account-type or entitlement verification**.
Output `received_at_utc` is local server clock time after reading, not an
attested clock or original exchange timestamp. For successful one-shot GETs,
`receipt_started_at_utc` and `receipt_completed_at_utc` bracket the HTTP
stream lifecycle using this process's wall clock, and the legacy
`received_at_utc` equals `receipt_completed_at_utc`. The separate
`receipt_elapsed_monotonic_ms` is a local monotonic-clock interval in
milliseconds, so it remains nonnegative even if UTC wall time jumps backwards.
These are **locally recorded bounds, not independently authenticated vendor
issuance, trusted UTC custody, candle timestamps, network-only latency, or
proof of feed freshness**. `receipt_clock_attested=false` always; a host clock
adjustment can make the two UTC labels appear reversed. The additional
`receipt_wall_elapsed_ms` and `receipt_wall_vs_monotonic_delta_ms` compare
local wall-clock elapsed time with monotonic elapsed time. A backwards wall
clock or a discrepancy greater than **2,000 ms** sets
`receipt_clock_anomaly_detected=true`; the threshold is a diagnostic heuristic,
not an independent time reference. A false anomaly flag is **not** evidence of
correct UTC, authenticated broker issuance or fresh market prices. These
observations never authorize a trade, retry, polling or source activation. Invalid/failed reads
return no receipt payload, and no timing data is persisted or transmitted.
Output always has
`account_type_verified=false`, `server_clock_attested=false`,
`market_data_feed=false`, `price_freshness_verified=false`,
`cfd_supported=false` and `may_execute_order=false`.

## Owner-only local example (do not commit keys)

After generating a properly scoped API key pair in an eligible account, pass
credentials from a secure runtime secret store. Do not paste secrets in issues,
PRs, logs, screenshots, or chat. The following is intentionally **not**
automatically invoked:

```python
import os
from app.trading212_readonly import fetch_trading212_readonly

result = fetch_trading212_readonly(
    endpoint="instruments",
    account_type="INVEST",
    environment="DEMO",
    api_key=os.environ["T212_API_KEY"],
    api_secret=os.environ["T212_API_SECRET"],
)
assert result["may_execute_order"] is False
```

Account summary responses may contain sensitive financial information. Restrict
their use to an authenticated owner-only service and never log or publicly
display the `data` field. No UI route, API key management, rate-limit scheduler,
persistent store or public data endpoint has been added.

Run isolated mocked tests without any credentials or network:

```sh
cd backend && PYTHONPATH=. pytest -q tests/test_trading212_readonly.py
```

## Activation / release blockers

Before connecting a real account: owner-controlled scoped read-only keys,
independent account-type verification, secure secret lifecycle, least-privilege
server authorization, explicit retention/redistribution rights, redacted audit
logs, per-account rate-limit management and account disconnect/revoke tests.
Before using any market feed: separately verify official instrument and venue
identities, authenticated completed bars, expected session/calendar population,
independently trusted clock, freshness, correction/replay handling, and licensing.
Do not use account metadata as market prices.

This is a disconnected optional integration, **not** a production activation.
PR #65 remains draft pending full CI, main reconciliation, production recovery,
rollback and post-deploy health verification. No live-money order code is enabled.


## Rate-limit response evidence (offline-tested, not account-verified)

Successful HTTP 200 reads now include a sanitized `rate_limit_observation` from
the official documented `x-ratelimit-limit`, `x-ratelimit-period`,
`x-ratelimit-remaining`, `x-ratelimit-reset` and `x-ratelimit-used`
response headers. The adapter never copies arbitrary headers, Authorization,
cookies, keys or secrets into this field. It rejects malformed/duplicate
counter values; absent, incomplete or internally inconsistent counters are
explicitly marked `MISSING_REVIEW_REQUIRED`,
`PARTIAL_REVIEW_REQUIRED` or `INCONSISTENT_REVIEW_REQUIRED`.
An internally consistent set is only `OBSERVED_UNVERIFIED`.

Every outcome has `account_quota_verified=false` and
`safe_to_make_another_request=false`. This is **not** a rate limiter, a
provider-signed receipt, a guarantee of account capacity or authorization for
a second call. The broker documents rate limits **per account across API
keys**; other clients may consume capacity between observations. There is no
automatic retry, polling, subscription or call to an account with this change.

Official reference (rechecked 26 October 2026):
https://docs.trading212.com/api

Mock-only regression tests:
`cd backend && PYTHONPATH=. pytest -q tests/test_trading212_readonly.py`.
Do not turn header observations into permission to spend provider credits or
into market-price freshness, live status or execution authority.


## HTTP Date/Age receipt provenance (untrusted, offline-tested)

A successful GET also includes `http_time_observation`. This is a bounded
observation of the response's **HTTP Date and Age headers**, not an attested
provider issuance timestamp or independently verified feed clock. It never
replaces `received_at_utc` and cannot authorize trading or enable a market feed.

- A single canonical IMF-fixdate `Date` is converted to
  `http_date_utc`; a missing Date yields
  `MISSING_DATE_REVIEW_REQUIRED`. Duplicate, malformed or noncanonical Date
  headers fail closed with sanitized errors.
- An optional single nonnegative decimal `Age` becomes
  `http_age_seconds`. A positive Age indicates the HTTP response may have
  passed through a cache; it is **not** evidence of fresh market data. Missing
  Age is not evidence of no caching. Duplicate or malformed Age fails closed.
- `local_completion_minus_http_date_seconds` compares the asserted Date to
  this process's untrusted completion wall clock. A difference over 300 seconds
  in either direction yields `LOCAL_CLOCK_DISAGREEMENT_REVIEW_REQUIRED`.
  The threshold is a heuristic; it cannot identify which clock is wrong.
- `http_date_attested=false`, `cache_freshness_verified=false`, and
  `may_use_as_market_timestamp=false` always. A Date header can be
  generated by a proxy, cache, intermediary or broker server and is not a
  cryptographic vendor receipt. Even a zero Age and a matching Date do not
  verify source authenticity, trading-session coverage, entitlement, quote
  freshness or executable bid/ask.

This check makes **no additional requests**, uses only headers already received
in the explicitly requested GET, and never logs keys, arbitrary headers or
account payloads. Synthetic tests cover missing, aged, stale, malformed and
duplicate header cases. It does not enable CFD access: Trading 212's official
public API remains Invest/Stocks ISA only (checked 29 October 2026):
https://docs.trading212.com/api.


## Strict JSON wire framing (mock-tested, not source authentication)

The optional GET-only adapter rejects ambiguous or unsupported HTTP response
metadata **before** consuming account data:

- Exactly one `Content-Type` must declare `application/json`; an optional
  `charset=utf-8` (including quoted UTF-8) is accepted. Other charset
  declarations, unsupported media parameters and duplicate media fields fail
  closed. The body is always decoded as strict UTF-8.
- An absent or single `identity` `Content-Encoding` is accepted. Compressed,
  comma-joined or duplicate coding declarations fail closed; decompression is
  never attempted.
- At most one decimal `Content-Length` is accepted, with the existing 8 MiB
  maximum. Duplicate or comma-joined lengths are rejected even when identical.
  If declared, the length must match the actual raw response bytes.

This reduces ambiguity between declared transport framing and the bytes hashed
in `response_sha256`. It does **not** verify broker signatures, TLS endpoints
beyond the normal client validation, market prices, timestamps, rights,
account eligibility or trading permissions. The adapter remains disconnected
and never retries, polls, stores credentials or sends orders.

Synthetic header regressions cover invalid/duplicate declarations and valid
UTF-8 variants. No real Trading 212 account or provider feed was accessed.
Official API scope checked 29 October 2026:
https://docs.trading212.com/api (Invest/Stocks ISA, not CFDs).
