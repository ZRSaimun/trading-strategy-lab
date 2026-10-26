# Forecast alert health audit (disconnected, read-only)

`app.forecast_alert_health_audit.audit_forecast_alert_health` provides a bounded,
side-effect-free backlog/latency census over a **declared** population of
`ForecastAlertOutbox` states. It makes **no** database, HTTP, Telegram, broker,
order, credential or market-data calls. It is not installed in an application
route or worker.

Pass a list of `{"sessionId": session_id, "state": state}` rows where each
`state` was independently decoded and validated by
`ForecastAlertOutbox._unpack(raw, as_of)` from an authorized, read-only database
snapshot. Pass a separately enumerated `expected_keys` list of
`(session_id, forecast_id)` pairs. Duplicate, missing, extra or malformed
records reject the whole audit. Inputs are bounded at 1,000 records. This
inventory is **caller-declared**, not cryptographically authenticated or proven
complete; even a matching population is not evidence that no alerts were omitted
upstream. Do not expose raw outbox records to unauthenticated clients.

The report distinguishes queued, expired-unclaimed, in-flight-uncertain,
self-attested ACK and cancelled records. It flags aged forecasts still queued (measured from issuance, not actual queue insertion,
which the existing outbox does not record) and uncertain claims requiring operator reconciliation. A self-attested ACK is **not** proof
of Telegram API acceptance, device delivery or human reading. Uncertain claims
are **never** automatically retried. The report always sets notification and
trading permissions false and cannot establish a live source, executable quote,
profit, calibrated forecast, or paper fill.

Use with an independently registered expected-population inventory, durable
outbox claim/transport receipts and trusted server timestamps. Do not activate
network sends until Loop 1 supplies authenticated entitled completed-candle
receipts, recipients explicitly opt in, and a separate authorized delivery
worker implements one-time claims, provider correlation and crash recovery.
Production backup restore, rollback and post-release health checks remain
separate release gates. Synthetic tests cover census integrity and latency
classification only; no real notifications or trades are made.

## Expiry-aware audit (26 October 2026)

An in-flight uncertain claim observed at or after its forecast expiry is
counted both as `IN_FLIGHT_UNCERTAIN` and
`EXPIRED_IN_FLIGHT_UNCERTAIN`; it remains **non-retryable**. A self-attested
ACK timestamp at or after the alert's expiry increments
`ACK_AT_OR_AFTER_EXPIRY_WARNING` and forces operator review, without
claiming provider or recipient delivery. Multiple warnings for one alert yield
one `warningKeys` entry. These warning counters overlap their underlying
status counts and must **not** be summed as mutually exclusive populations.

The standalone audit rejects impossible zero-lifetime or greater-than-one-hour
outbox expiries before producing any health report. This mirrors the
`ForecastAlertOutbox.queue` age limit; it is **not** a substitute for journal
reconciliation, which additionally checks the target candle close. A valid
one-hour upper bound does not establish authentic market data or delivery.

The expiry comparison uses the caller-supplied `as_of` and stored timestamps;
neither is cryptographically attested. An ACK timestamp before expiry is still
not proof of delivery or timely reading. This change remains read-only and
does not enable any sender, paper fill, broker order, or production deployment.
