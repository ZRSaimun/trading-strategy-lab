# Loop 5: declared forecast issuance coverage (offline, disconnected)

`audit_forecast_issuance_coverage(snapshot, expected_identity, expected_keys, as_of=...)` compares a **separately declared** model/horizon/base-candle issuance register with a replay-validated `ForecastEventStore.load` snapshot. This closes a visibility gap: settled-only calibration and alert-health reports cannot detect a forecast that was never issued.

Each expected key is `(modelVersion, horizonCandles, baseStart)`, with horizons 1, 3 or 12. The caller must independently determine which completed source candles and model/horizon combinations **should** have produced forecasts; skipped market sessions and intentional model abstentions must be represented in that schedule. The function does **not** assume every completed candle requires a forecast, infer sessions or generate missing forecasts.

Validation is fail-closed: strict source identity, bounded 5,000-key register, unique model/horizon/base keys, aligned and completed base candles, no future issuance at the declared cutoff, and strict preexisting journal scorecard validation. A duplicate expected or observed issuance, malformed source, future cutoff violation, or forged journal evidence raises `ValueError`. A well-formed mismatch reports `OPERATOR_REVIEW_REQUIRED` with exact missing/unexpected counts and the first 50 sorted keys from each side; large lists are explicitly truncated. An empty register reports `NO_DECLARED_EXPECTATIONS`, never a completeness certificate. Pending and void outcomes still count as **issued** forecasts; they are not counted as settled, delivered or profitable.

A matching declared register returns `DECLARED_MATCH_UNVERIFIED`, **not** authenticated coverage. The expected register, UTC cutoff, vendor entitlement, candle timestamps and journal are caller-declared. This audit cannot detect missing forecasts if the register is derived from the same incomplete journal; independent Loop 1 completed-candle and model-schedule receipts are required. It neither sends alerts nor records paper fills, changes source data, accesses brokers or permits live orders. Every authorization flag is false.

Run synthetic tests: `cd backend && PYTHONPATH=. pytest -q tests/test_forecast_issuance_coverage.py`.

**Release gate:** Keep draft/unmerged/undeployed pending exact-head full CI, independent schedule and feed attestation, genuine forward reconciliation, restored backup, rollback rehearsal and authenticated production health. No claimed forward P&L, downside-adjusted returns, or financial drawdown.
