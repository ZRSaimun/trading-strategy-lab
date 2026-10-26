# Loop 5 — frozen recency-weighted probabilistic challenger (disconnected)

This additive **research-only** candidate is deliberately separate from the existing equal-weight Jeffreys baseline in `backend/app/forecast_causal_issuer.py`. It does **not** authenticate a market provider, schedule a worker, enable an alert transport, fetch executable quotes, generate broker orders or demonstrate a trading edge. It is not enabled on Render.

## Frozen hypothesis and causal issuance

The target is `P(close[t+h] > close[t])` for `h = 1, 3, 12` completed candles of the **same exact source/side/instrument identity**. `decayed_training` uses only fully observed outcomes, requires every intermediate completed candle, and takes disjoint UTC-phase-aligned training bases (`floor(start/seconds) % h == 0`). For each horizon, oldest-to-newest eligible outcomes receive weights `2^(-age/128)` (age is counted in eligible outcomes, not calendar time). With Jeffreys pseudo-counts `(weighted_up + 0.5) / (sum_weights + 1)`, issuance abstains unless `n >= 30` and Kish effective sample size `(sum_weights)^2 / sum(weights^2) >= 20`. Constants are frozen in `jeffreys-decay-utc-phase-v1-hl128-n30-ess20`; tuning requires a new declared model version and untouched forward evaluation. Fixed-phase disjoint outcomes reduce within-horizon label overlap but **do not prove independence**. This is an uncalibrated probability estimate.

The `CausalDecayChallenger` consumes only `ForecastEventStore.load()` output for the **latest already-persisted completed candle**, not caller-supplied prices or historical imports. It appends at most one batch of three horizon forecasts through the existing `append_forecasts_atomic` optimistic-CAS/audit primitive, using deterministic model-specific IDs. Repeated calls are idempotent; changed probabilities or identifiers fail closed. Existing issuance deadlines and stale-candle checks remain enforced by the event store. Callers must invoke it only after independently authenticated, entitled prospective candle ingestion has committed; a direct invocation on a synthetic journal is *not* operational live forecasting.

Example for **offline synthetic** evaluation, after an existing authorized writer has persisted a candle:

```python
from app.forecast_decay_challenger import CausalDecayChallenger
challenger = CausalDecayChallenger(store, session_id, exact_identity, max_lag_seconds)
result = challenger.issue_for_latest(last_persisted_candle_start)
assert result["live"] is False and result["ordersSubmitted"] == 0
```

The challenger may be compared against the baseline only on **paired, prospectively issued, settled observations**. Apply the existing coverage, maturity, scorecard, drift and frozen-baseline audits, with chronological evaluation and overlapping-outcome dependence disclosed. No retrospective replay should be labelled prospective. Model selection must not use the final holdout, and neither Brier-score improvements nor directional accuracy imply positive net trading expectancy.

## Tests, risk and handoff

`cd backend && PYTHONPATH=. pytest -q tests/test_forecast_decay_challenger.py` covers 25 synthetic unit cases plus one real SQLite event-store integration case, including fixed phases, gap exclusions, strict malformed-input rejection, minimum sample abstention, 1/3/12 horizons, bounded probabilities, atomic batch composition, duplicate/idempotent restart, partial retry, source mismatch, changed-model refusal and CAS conflict. A fake store exercises the orchestration contract, while the SQLite case verifies persisted atomic issuance and idempotent restart. These tests do **not** prove PostgreSQL process-kill recovery or real provider delivery. The real `ForecastEventStore` owns DB transaction and clock enforcement.

Loop 1 must supply authenticated/entitled completed-bar receipts, source and side identity, independently expected-bar census, trusted receipt clock, session-aware gap policy and archival isolation. Live BID/ASK quote receipts and independently reconciled spread, fees, slippage, financing and drawdown are required before paper-fill performance can be asserted. Reliable notifications additionally require an authenticated destination, durable transport, receipt verification and consent. No live order path is enabled; each eventual real-money order still requires supported eligible broker API/account, current executable quote, risk caps and specific owner confirmation. Keep this PR draft until exact-head CI, branch reconciliation, backup restore, rollback and health are independently verified.
