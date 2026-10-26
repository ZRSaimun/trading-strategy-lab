# Bounded OANDA v20 practice transaction-range preflight

`backend/app/oanda_practice_transaction_range.py` extends the **draft**, opt-in `OandaPracticeReadOnly` inspection component with a single bounded `GET /v3/accounts/{accountID}/transactions/idrange?from=...&to=...` operation. It never creates, modifies, closes or cancels orders. The official [OANDA transaction API documentation](https://developer.oanda.com/rest-live-v20/transaction-ep/) specifies this GET endpoint and the `transactions` and `lastTransactionID` response fields. Only the fixed fxPractice host is permitted by the existing adapter; there is no live host, route, scheduler, storage or credentials configuration.

```python
from datetime import datetime, timezone
from app.oanda_practice_readonly import OandaPracticeReadOnly
from app.oanda_practice_transaction_range import read_practice_transaction_range

# Only with owner-authorized OANDA v20 practice credentials, on a private host.
client = OandaPracticeReadOnly(practice_account_id, secret_token, enabled=True)
report = read_practice_transaction_range(client, "100", "150", as_of=datetime.now(timezone.utc))
```

The call rejects noncanonical IDs, reversed/zero/unbounded ranges (>100 IDs), malformed account IDs, naive cutoffs, duplicate/out-of-range/out-of-order IDs, account mismatch, invalid transaction type/time, future nanosecond timestamps, time regression and a response cursor behind the requested range. Missing IDs are counted, not invented. The existing `_get` enforces disabled-by-default network, GET-only practice-host transport, a 5-second timeout, no redirects, no environment proxies and a 256-KiB response ceiling. All caller input is checked before the request. This companion uses the adapter's internal `_get` method; any refactor of that method requires joint review.

The returned SHA-256 is computed from **canonicalized JSON**, not original HTTP bytes, broker signature, or independently retained evidence. The report intentionally omits transaction payloads (which may contain sensitive account details), and explicitly marks original-byte authentication, complete history, cash reconciliation and order permissions **false**. A contiguous observed ID range is not proof of complete statements or actual fills. OANDA may have legitimate transaction ID gaps, and no gap is silently filled. Transactions can be added after a read; a snapshot is not atomic across independent summary, price and transaction requests. No settlement, financing, commission, FX conversion or net-profit claim is made.

Tests: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_oanda_practice_transaction_range.py`. Synthetic fixtures and a fake `_get` verify deterministic validation and request construction without any external network. Full exact-head CI is required before release. This remains a draft, offline-only research extension until the production release gate is independently verified.
