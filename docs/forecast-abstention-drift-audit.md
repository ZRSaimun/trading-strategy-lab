# Offline chronological forecast-versus-abstention drift audit

`app.forecast_abstention_drift_audit.audit_forecast_abstention_drift` is a **disconnected, read-only, declared-evidence diagnostic** for prospective forecasting research. It first replays the existing `audit_forecast_decision_coverage` validation and requires every independently *declared* expected model/horizon/completed-candle decision to reconcile to exactly one forecast or explicit abstention. A missing, unexpected or contradictory decision withholds **all** rates, rather than silently shrinking the denominator.

For each `(modelVersion, horizonCandles)` with at least 60 chronological expected decisions (default minimum 30 per half), the audit splits by **base-candle start time**, not journal insertion order. It reports the early and late declared abstention fractions, late-minus-early difference, reason counts and an operator-review warning if the absolute difference exceeds 0.20 (configurable 0–1). Odd populations use `floor(n/2)` early and the remainder late. Models and 1/3/12-candle horizons are never pooled. Inadequately populated groups have no estimated rates. Even when every group is below threshold, the result is explicitly **UNVERIFIED**, not evidence of model stability or significance. The threshold is a descriptive monitoring heuristic, not a hypothesis test or a trading rule.

```python
from app.forecast_abstention_drift_audit import audit_forecast_abstention_drift

report = audit_forecast_abstention_drift(
    snapshot, expected_identity, expected_keys, abstentions,
    as_of=declared_utc_epoch_seconds, min_per_half=30, warning_fraction=.20,
)
```

This code has no database, network, alert sender, broker adapter, money access or production data writes. It cannot prove the caller-declared schedule was preregistered, timestamps are server-owned, abstentions were independently witnessed, market candles are authentic, or alerts reached a recipient. No historical BID candle is an executable quote. **Never enable notifications, paper fills or real-money orders from this report.** Loop 1 must supply licensed authenticated prospective completed-candle receipts, source/side/venue lineage, independently registered session-aware model/horizon schedules, server-owned UTC timestamps, and append-only forecast/abstention records before operational evaluation. Keep this isolated draft unmerged and undeployed pending exact-head CI, independent backup restoration, rollback and authenticated production health checks.
