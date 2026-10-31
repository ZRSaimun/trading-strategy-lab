# Offline completed-candle decision latency census

`app.forecast_decision_latency_audit.audit_forecast_decision_latency` is a **disconnected, read-only research/operations audit**. It takes a replay-validated `ForecastEventStore.load` snapshot, an independently *declared* model/horizon/completed-base-candle schedule, explicit abstentions, and a declared evaluation cutoff. It first invokes `audit_forecast_decision_coverage`, so invalid source identity, duplicate issuances, inconsistent forecast events, malformed abstentions and contradictory decision populations fail closed or trigger operator review.

For each expected decision it measures the time between the completed base candle's close and the journal's `issuedAt` or the declared abstention's `decisionAt`. A decision with latency **equal to** the warning budget is within budget; a later decision is counted as late. Missing decisions are divided into *still within the permitted decision window* and *past the deadline*. The latter requires the declared `as_of` to be strictly later than the last permitted timestamp, bounded by both `maxLagSeconds` and the following candle's start. Missing decisions never silently disappear from the denominator.

The audit reports counts, a within-budget fraction over **all expected keys**, and a bounded list of overdue keys. Nearest-rank p50/p95 and maximum recorded latency are withheld unless the *entire* expected population is reconciled without missing, conflicting or unexpected decisions and has at least 30 records (configurable 30–5,000). Horizon-specific percentiles have their own minimum support. The three horizons are 1, 3 and 12 candles. These are descriptive declared-clock metrics, not SLA compliance, forecast accuracy or financial performance.

Example usage (all values synthetic and unauthenticated):

```python
from app.forecast_decision_latency_audit import audit_forecast_decision_latency

result = audit_forecast_decision_latency(
    snapshot, expected_identity, expected_keys, abstentions,
    as_of=declared_utc_epoch_seconds, warning_seconds=15,
)
```

**Do not enable alerts or trades from this result.** Neither forecast timestamps nor abstention timestamps, schedule provenance, provider data, recipient delivery or server-clock custody are independently attested. The audit performs no network calls, sends, broker requests, database writes, fills, or orders. Historical BID-only candles are not executable quotes. Operational use requires Loop 1's authenticated prospective completed-candle receipts, source/side/venue lineage, server-owned UTC clock and session-aware expected schedule, plus independently witnessed abstention and notification receipts. Keep draft/unmerged/undeployed until exact-head CI, staging and independently verified backup restoration, rollback and authenticated health checks are complete.
