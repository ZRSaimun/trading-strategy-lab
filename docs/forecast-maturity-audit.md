# Loop 5 — disconnected forecast maturity / censoring audit

`backend/app/forecast_maturity_audit.py` is a **read-only offline research diagnostic** for a snapshot returned by `ForecastEventStore.load`. It has no route, worker, data feed, notification transport, credentials, broker order or database mutation. The caller must authenticate any eventual source independently and supply a trustworthy server-controlled `as_of` for operational use; the present result explicitly marks that time **unverified**.

The audit groups by exact model version and horizon (1/3/12 completed candles). It distinguishes settled outcomes, gap-voided forecasts, pending forecasts whose target has not yet passed the declared completion/receipt/grace budget, and pending forecasts that have exceeded that budget without a recorded outcome. `maturedOrOverdue` is settled + void + overdue. `settledFractionOfMatured` is a **coverage diagnostic**, not directional accuracy or trading profitability. A `requiresReconciliation` flag indicates overdue or gap-voided records. A market closure can make a forecast appear overdue: **this is not proof of missing market data**. Reconcile exchange sessions and provider outages before interpreting any result.

Example (with an already validated snapshot):

```python
from app.forecast_maturity_audit import audit_forecast_maturity
report = audit_forecast_maturity(store.load(session_id), as_of=server_epoch_seconds)
```

Use `cd backend && PYTHONPATH=. pytest -q tests/test_forecast_maturity_audit.py`. Synthetic tests cover exact maturity boundaries, grace, horizon separation, gap-vs-settlement accounting, malformed source linkage, future/early resolution, and invalid clocks. No forward returns, broker fills, drawdown, live quotes, calibrated edge, or alert delivery are established. Historical BID prices are not executable broker quotes.

**Loop 1 handoff:** supply authenticated completed-candle receipts, source entitlements, exact instrument/price-side identity, provider sequence/receipt evidence, server time, and an authoritative market-session/holiday calendar. Until these are independently validated, do not activate alerts or paper fills from this diagnostic. Preserve production data, verify backup restore/rollback/health before any deployment, and require owner approval for every real-money order.
