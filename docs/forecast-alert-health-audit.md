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
are **never** automatically retried. Every `IN_FLIGHT_UNCERTAIN` record is
included in `warningKeys` immediately upon claim, even before the
`UNCERTAIN_DELAY_WARNING` threshold; otherwise the operator-review status
could lack the identities needing reconciliation. The delay counter still
fires only at its configured age boundary. `warningKeys` are deduplicated
and are not proof of a Telegram delivery failure. The report always sets notification and
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

## Pre-expiry queue warning (26 October 2026)

The read-only audit now flags an **unclaimed, still-valid** alert when its
remaining lifetime is at most `expiry_warning_seconds` (default 30 seconds,
configurable from 1 to 3,600). The `EXPIRING_SOON_WARNING` counter is separate
from `QUEUE_DELAY_WARNING`: short-lived alerts can be at risk of expiring
before their issuance-age queue threshold is reached. At exact expiry the
record is `EXPIRED_UNCLAIMED` instead, never `EXPIRING_SOON_WARNING`.
Overlapping warnings for one record yield only one `warningKeys` identity.

This is an **operator-review signal**, not authorization to rush a send or
bypass entitlement, completed-candle verification, recipient opt-in or durable
claim reconciliation. The report remains caller-declared and does not measure
real notification delivery, forecasting accuracy, paper returns or trading
profitability. No sender or order execution is activated.


## Target-completion and causal issuance bounds (26 October 2026)

The disconnected health census now independently rejects an outbox state whose
base start is not candle-aligned, whose issuance is before the completed base
candle or at/after the next candle completion, or whose expiry exceeds the
forecast target candle's completion (baseStart + (horizon + 1) * seconds).
It also rejects target-end timestamp overflow. These bounds mirror the
prospective ForecastEventStore issuance window and ForecastAlertOutbox.queue
expiry clamp, rather than trusting a caller-declared alert TTL alone.
The pre-existing one-hour TTL limit still applies. Synthetic regression cases
cover invalid chronology and the exact valid target-end boundary; a legitimate
one-hour TTL is tested with a sufficiently long candle interval.

This is a read-only audit, not an authentication or sending gate. A caller can
still omit records, supply a false as_of, or lack independent expected-bar
inventory. It never turns historical BID candles into live quotes, authorizes
notification delivery, places paper/live orders or proves profitable returns.

## Self-attested ACK reconciliation inventory (28 October 2026)

The read-only census now exposes `unverifiedAckKeys` as a sorted list of
`[sessionId, forecastId]` identities for **every**
`ACK_RECORDED_UNVERIFIED` outbox state, including timely ACKs with no age or
expiry warning. Its length equals the existing
`counts.ACK_RECORDED_UNVERIFIED`. This makes the pending independent
provider/recipient reconciliation population visible to operators rather than
requiring them to reconstruct identities from raw persisted records.

`unverifiedAckKeys` is deliberately **separate** from `warningKeys`: a timely
self-attested ACK is not automatically a latency incident, and existing health
status semantics are unchanged. An ACK at or after expiry appears in both lists.
The inventory is caller-declared and neither proves acceptance nor delivery;
there is no automatic retry, notification authority, paper fill, broker order,
route, or production activation. Synthetic tests cover mixed and reordered
populations, timely ACKs, expired ACKs and empty ACK inventories.

## Deterministic warning-reason inventory (28 October 2026)

The read-only census now includes `warningReasons`, a sorted list of objects
`{"key": [sessionId, forecastId], "reasons": [reason, ...]}` for exactly the
identities in `warningKeys`. Reasons are sorted, deduplicated status/warning
codes from the existing classification logic. A queued alert can carry both
`QUEUE_DELAY_WARNING` and `EXPIRING_SOON_WARNING`; an uncertain claim always
carries `IN_FLIGHT_UNCERTAIN` and may also carry delay/expiry reasons. This
allows operators to triage each alert without reverse-mapping overlapping
aggregate counters. `unverifiedAckKeys` remains separate for timely ACKs;
a late self-attested ACK appears in both inventories. No underlying status,
warning threshold, retry, notification, or order authority changes. Both
inventories remain caller-declared and require independent reconciliation.
