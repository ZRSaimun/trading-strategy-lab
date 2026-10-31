# OANDA v20 fxPractice read-only inspection (opt-in, no orders)

`backend/app/oanda_practice_readonly.py` implements two GET-only v20 **practice-host** calls: account summary and current account-specific BID/ASK pricing. The fixed host is `https://api-fxpractice.oanda.com`; it has no order, trade, modify, cancel or live-host methods. Network is **disabled by default**. It is a small optional research component, **not wired into API routes, scheduled polling, trading strategies or execution**.

Official documentation: [development guide](https://developer.oanda.com/rest-live-v20/development-guide/), [account summary](https://developer.oanda.com/rest-live-v20/account-ep/), [pricing](https://developer.oanda.com/rest-live-v20/pricing-ep/) and [authentication](https://developer.oanda.com/rest-live-v20/authentication/). Availability, instruments and regulatory permissions depend on the individual OANDA v20 account. No Trading 212 CFD API is assumed.

```python
# Explicitly opt in only on a private, authorized machine with a real
# OANDA v20 practice account. Do not log tokens, responses or account IDs.
from datetime import datetime, timezone
from app.oanda_practice_readonly import OandaPracticeReadOnly
adapter = OandaPracticeReadOnly(practice_account_id, secret_token, enabled=True)
summary = adapter.account_summary()
quotes = adapter.pricing(["EUR_USD"], as_of=datetime.now(timezone.utc), max_age_seconds=5)
```

The adapter checks practice account ID/currency/transaction cursor, bounded nonnegative balance/NAV/margin, exact decimal top-of-book bid/ask, requested instrument coverage, tradeable status, future/stale timestamps and crossed quotes. HTTP redirects, non-200, oversized and malformed responses fail closed. TLS verification and bounded timeouts use httpx; environment proxies are disabled. Only allowlisted GET paths are constructed. The token is never placed in returned dictionaries or repr. Never store it in the repository.

**Limitations:** A successful practice API response is not proof of independently executable liquidity, fills, queue priority, correct CFD financing, cash settlement, an authenticated multi-year historical dataset, or profitability. The supplied `as_of` is caller-declared and does not prove local clock synchronization. Quotes are snapshots, not a full tick tape. This does not validate the completeness of transactions or reconcile positions; it is not a paper-order sender or live-order-ready integration. The account-specific instrument availability must be verified separately before treating any symbol as supported.

Tests: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_oanda_practice_readonly.py`. All tests use `httpx.MockTransport` with invented data and **make zero external broker calls**. No real-money order path is created.
