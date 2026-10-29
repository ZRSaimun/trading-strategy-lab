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


## Cross-alert claim-token uniqueness (28 October 2026)

The disconnected health census now **rejects reused non-null `claimId` tokens
across the entire declared outbox population**, including different sessions
and mixed `IN_FLIGHT_UNCERTAIN` / `ACK_RECORDED_UNVERIFIED` records.
Outbox claim tokens are intended to correlate a single attempt with one alert;
reusing a token could make a later transport receipt ambiguous even if the
`[sessionId, forecastId]` keys are otherwise distinct. An integrity failure
raises `ValueError` rather than emitting a superficially healthy census.
Unclaimed `QUEUED` and `CANCELLED` rows have null claim tokens and remain
valid. Synthetic tests cover cross-session collisions, mixed-status collisions,
and order-independent valid distinct tokens.

This is a **caller-declared collision check**, not cryptographic proof of
unique claim issuance, provider acceptance, device delivery, feed authenticity
or independent inventory completeness. The durable outbox and independent
claim/receipt reconciliation remain necessary. No sender, automatic retry,
paper fill, broker order or production route is enabled.


## Aged self-attested ACK reconciliation warning (28 October 2026)

A self-attested `ACK_RECORDED_UNVERIFIED` is **not** independent proof of
provider acceptance, recipient delivery or reading. Previously it could remain
in `unverifiedAckKeys` indefinitely without entering the actionable warning
inventory unless the ACK itself was late relative to forecast expiry.

The read-only census now accepts an optional `unverified_ack_warning_seconds`
(default 300; integer 1–3,600). At `as_of - ackAt >= budget`, it adds
`ACK_RECONCILIATION_OVERDUE_WARNING` to `counts`, `warningKeys` and
`warningReasons`, and returns `OPERATOR_REVIEW_REQUIRED`. The report also
includes `oldestUnverifiedAckAgeSeconds` (zero for an empty ACK population).
A late ACK can carry both late-ACK and aged-reconciliation warnings, so these
counters overlap and must not be added as disjoint populations. Timely ACKs
within the budget remain in `unverifiedAckKeys` but do not trigger this warning.

The age is computed from **caller-declared** `ackAt` and `as_of`; it is not
an independently attested delivery latency. This is for human reconciliation
only: no automatic resend, notification sender, broker adapter, paper fill,
order execution, production route or deployment is enabled. Synthetic tests
cover exact age boundaries, budget overrides, empty populations, deterministic
mixed records, overlapping warnings and invalid budgets.


## Earliest active queue expiry triage (28 October 2026)

The read-only health census now returns
`earliestQueuedExpirySecondsRemaining` and `earliestQueuedExpiryKeys`.
Only still-valid, unclaimed `QUEUED` rows participate. The countdown is
`expiresAt - as_of`, strictly positive; at exact expiry the row is instead
`EXPIRED_UNCLAIMED` and excluded. All ties for the nearest expiry are returned
as sorted `[sessionId, forecastId]` identities. Empty, cancelled, expired,
uncertain-claim and ACK-only populations return `null` for the countdown and
an empty key list. Results are independent of record ordering.

These caller-declared expiry deadlines help an operator triage a backlog; they
do not authenticate a server clock, prove complete registration, establish
provider/device delivery, grant permission to send, retry uncertain attempts,
execute paper/live orders or bypass entitlement/opt-in gates. The metric is not
a delivery SLA or trading-performance measure.


## Oldest unverified ACK identities (28 October 2026)

The read-only health report now includes `oldestUnverifiedAckKeys`, a
deterministically sorted list of all `[sessionId, forecastId]` identities tied
for `oldestUnverifiedAckAgeSeconds`. This closes an operator triage gap: the
previous oldest-age metric did not identify which acknowledgement(s) needed
independent reconciliation. All ACKs remain in `unverifiedAckKeys`, including
those younger than the oldest; the new list is not an independent delivery
receipt. A zero-age ACK is still listed, while an empty ACK population returns
an empty list and zero age. Ordering and ties do not depend on input order.

The age is calculated only from caller-declared `ackAt` and `as_of`. It does
not prove provider acceptance, device delivery, human reading, or a live
market feed. No send/retry, paper fill, live order, worker, route or deployment
is enabled. Synthetic regressions cover ties, mixed populations, empty
populations and the exact zero-age boundary.


## Next unverified ACK escalation deadline (28 October 2026)

The disconnected, read-only census now includes
`nextUnverifiedAckEscalationSecondsRemaining` and
`nextUnverifiedAckEscalationKeys`. Among self-attested ACKs still *within*
the configured reconciliation budget, these identify the nearest upcoming
operator-review escalation and all tied `[sessionId, forecastId]` keys.
If there are no such ACKs, the countdown is null and the keys list is empty.
At the exact threshold the ACK leaves this upcoming-deadline inventory and
enters `ACK_RECONCILIATION_OVERDUE_WARNING`/`warningKeys`. Already overdue
ACKs are never represented as zero-second upcoming deadlines.

This is a descriptive countdown using caller-declared timestamps, not a
scheduler, delivery proof, authenticated source, send/retry permission, or
trading signal. It does not activate workers, Telegram delivery, paper
execution, live broker access, or production deployment.


## Next queued-alert delay warning deadline (29 October 2026)

The disconnected read-only census returns
`nextQueueDelayWarningSecondsRemaining` and `nextQueueDelayWarningKeys`.
For still-valid, unclaimed `QUEUED` alerts **younger** than
`queue_warning_seconds`, these identify the nearest upcoming issuance-age
warning and all tied sorted `[sessionId, forecastId]` identities. The
countdown is a strictly positive integer. At the exact threshold the alert
instead enters `QUEUE_DELAY_WARNING`; expired queued alerts, uncertain
claims, self-attested ACKs and cancellations never enter the upcoming-deadline
inventory. With no eligible queued alerts, the countdown is null and keys
are empty. A separate `EXPIRING_SOON_WARNING` may already require operator
review even when the queue-age deadline is still in the future.

This metric uses only caller-declared issuance times and `as_of`. It does
not schedule or authorize a send, authenticate completed market candles or
recipient delivery, retry an uncertain claim, create a paper fill, or permit
broker orders. Three synthetic regressions cover ties and record-order
independence, mixed statuses, exact one-second/threshold/expiry boundaries,
and configurable warning budgets. Production release still requires
independent source and receipt evidence, recipient opt-in, and verified
backup restoration, rollback and health checks.


## Expiry-preempted queued-delay deadlines (29 October 2026)

A queued alert only has a reachable upcoming `QUEUE_DELAY_WARNING`
when `issuedAt + queue_warning_seconds < expiresAt`. At the exact expiry
timestamp, `EXPIRED_UNCLAIMED` takes precedence over the queue-delay warning;
therefore a queue-age threshold **equal to or later than expiry** must not be
shown as a future incident. Previously the audit advertised such impossible
countdowns even though the alert would expire first.

`nextQueueDelayWarningSecondsRemaining` and
`nextQueueDelayWarningKeys` now exclude expiry-preempted candidates.
An alert whose delay threshold falls strictly before expiry still appears,
including one second before the threshold; once breached it is counted in
`QUEUE_DELAY_WARNING` instead. `earliestQueuedExpirySecondsRemaining`
and the existing pre-expiry/expired warning classifications remain unchanged.
Synthetic regressions cover early expiry, equal expiry/threshold, strictly
reachable deadlines, mixed populations and order independence.

These are caller-declared timestamps, not a trusted scheduler or provider
delivery evidence. The correction grants no notification, retry, paper-order
or live-order authority and requires no production activation.
