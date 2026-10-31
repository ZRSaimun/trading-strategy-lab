# Offline economic schedule drift census

`app.offline_event_schedule_drift.audit_declared_schedule_drift_asof` is a disconnected, research-only diagnostic for **declared pre-release schedule changes**, not a trading signal or proof of a complete calendar.

It first invokes the strict revision validator in `offline_event_asof_guard`. Only schedules observed strictly before the historical decision minute enter the census. A forecast-only update counts as an unchanged-schedule revision, not a rescheduling. The auditor reports the first and latest visible schedule, number of changed release times, net signed schedule drift, cumulative absolute drift (so a postponement followed by a reversal does not disappear), largest individual shift, and age of the last reschedule. The age clock stops at the final scheduled event time after release. The threshold is an explicitly declared 0–1440 minute **descriptive** policy; cumulative absolute drift exceeding it is a diagnostic, never permission or a market prediction.

Outputs are source/cutoff/full-visible-history bound by the existing v2 envelope and a new deterministic `schedule_drift_audit_sha256`. This is a checksum, not independent proof of vendor receipts, completeness, event identity, calendar licensing or accuracy. A malformed future revision fails closed under the upstream validator even though it cannot enter an earlier snapshot. Exact-decision-minute observations are excluded. An empty inventory is unknown coverage, not an event-free market.

**Safety:** `research_only=True`, `trade_authorized=False`, `authenticated_calendar=False`, `coverage_verified=False`, `receipt_provenance_verified=False` in all outputs. Do not use a small/zero schedule drift to clear news risk, make pre-news predictions or enable paper/live orders. No production API, broker, external calendar, paid service or market archive is involved. Authentic original publication and receipt custody, source-local market candles, costed chronological holdouts and execution risk remain separate requirements.

Synthetic regression: `cd backend && PYTHONPATH=. python -m pytest -q tests/test_offline_event_schedule_drift.py`.
