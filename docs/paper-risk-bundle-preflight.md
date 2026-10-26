# Read-only paper risk bundle preflight (Loop 4)

`PaperRiskBundlePreflight.inspect` correlates three existing **unverified**
paper research records: a one-use order intent, a quote replay marker, and the
current UTC day's daily-loss latch. It reads the three records and the optional
atomic quote/journal owner marker in **one SQL SELECT**. Under PostgreSQL's
normal READ COMMITTED semantics, this avoids a torn view across separate
queries. It does **not** lock the records or prevent concurrent updates after
the SELECT; there is no execution path.

A coherent result still reports `HOLD_RECONCILIATION` and
`may_execute_paper_order=false`, `may_execute_real_order=false`.
Coherence means only that these declared records are mutually compatible at
the moment read; it does **not** authenticate any provider, prove full account
inventory, verify a protective stop, reserve cash, certify a fill, or establish
human consent.

Checks include exact account/quote-source identity, order-review digest,
one-use intent status and expiry, quote marker age/time order/transport delay,
daily-loss observation freshness and monotonic latch, and whether the quote
source is owned by an atomic journal. A bound source is held for separate
journal reconciliation; missing/corrupt/oversized evidence fails closed.

**No API route, credential storage, broker HTTP client, live-order sender,
risk-reservation release, migration, production data write or paid action.**
The output fingerprint is an unkeyed diagnostic SHA-256, not a signature or
permission token. The module intentionally does not write audit records because
it is a read-only preflight; the underlying stores audit their own mutations.

Example from `backend/`:

```python
from app.paper_risk_bundle_preflight import PaperRiskBundlePreflight

report = PaperRiskBundlePreflight().inspect(
    "paper-account-001", "client-order-001",
    {"account_alias": "paper-account-001", "provider": "DemoProvider",
     "venue": "DEMO-OTC", "instrument": "XAUUSD-DEMO"},
    review_sha256="<64 lowercase hex characters>",
    now_ms=server_clock_utc_milliseconds,
)
assert not report["may_execute_real_order"]
```

The server clock must be trusted. Do not accept client-provided time or
unverified data as broker proof. A legacy journal forward-binding without a
reverse owner marker cannot be established from this four-key snapshot;
the permanent HOLD result must remain in place until authenticated journal
and broker reconciliation are implemented.

## Acceptance and release

Run `PYTHONPATH=. python -m pytest -q tests/test_paper_risk_bundle_preflight.py`
from `backend/`, then the full backend/frontend/PostgreSQL CI pipeline.
Before merging/deploying any integrated workflow, require a disposable
PostgreSQL concurrency test, process-crash recovery, confirmed production
backup restoration, rollback and post-deploy health verification.

Trading 212 public API documentation (checked 26 Oct 2026):
https://docs.trading212.com/api — supports Invest/Stocks ISA, not CFD.
No real-money execution is supported or authorized by this component.
