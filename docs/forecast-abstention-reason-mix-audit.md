# Declared forecast abstention reason-mix drift audit

`backend/app/forecast_abstention_reason_mix_audit.py` exposes
`audit_forecast_abstention_reason_mix(snapshot, expected_identity, expected_keys, abstentions, *, as_of, ...)`.
It is a disconnected, read-only **research diagnostic**, not a market-data adapter,
notification service, paper broker, or live order approval.

The existing decision-coverage validator must first find exactly one forecast or
abstention for every declared model/horizon/base-candle key. Missing, unexpected,
contradictory or invalid decisions suppress **all** mix statistics. For each
model version and 1/3/12-candle horizon, expected decisions are sorted by
base-candle UTC epoch and split into first and second chronological halves.
Groups require at least 30 decisions and 20 abstentions in **each** half;
otherwise their conditional mix is withheld. Reason order is fixed:
`DATA_QUALITY`, `LOW_CONFIDENCE`, `MODEL_UNAVAILABLE`, `OTHER`, `POLICY_HOLD`.

The reported total-variation distance is half the sum of absolute differences
between normalized reason frequencies, ranging from 0 (identical) to 1
(disjoint). The default descriptive operator-review threshold is strictly
**greater than 0.25**; it is not a statistical significance test. Abstention
rates and decision counts are shown separately: stable conditional reason
composition does **not** establish stable abstention behavior or forecast skill.

**Evidence and activation:** Inputs and evaluation cutoff are caller-declared.
Passing a consistency audit does not independently authenticate market data,
source rights, UTC receipt clocks, schedules, abstentions, recipients or fills.
This module always returns false for notification, paper-order and live-order
authorization. Historical BID data are not executable quotes. No real orders,
notifications, external HTTP requests, database mutations, credentials or
production routes are involved. Before operational integration, Loop 1 must
supply independently authenticated prospective completed-candle receipts,
source/side/session provenance, server-owned UTC times and append-only
independently registered model/horizon decisions and abstentions.

Reproduce isolated tests from the repository backend:

```sh
PYTHONPATH=. python -m pytest -q tests/test_forecast_abstention_reason_mix_audit.py
```

The isolated tests use a stub for the already independently tested coverage
validator; full GitHub CI must exercise all real dependencies and cannot
substitute for independent production restore, rollback and authenticated
health checks. This audit does not establish forward accuracy, net paper P&L,
financial drawdown, profitability or broker API eligibility.
