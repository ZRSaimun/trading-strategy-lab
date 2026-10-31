# Loop 5 — Offline forecast-alert lifecycle integration rehearsal

This is a **synthetic, no-network integration acceptance test**, not an
operational notification sender or proof of forward profitability.

Run from `backend`:

```sh
PYTHONPATH=. python -m pytest -q tests/test_forecast_alert_pipeline_rehearsal.py
```

The test constructs a disposable SQLite database and drives the existing
`ForecastEventStore`, `ForecastAlertOutbox`,
`render_unverified_forecast_review` and `send_telegram_once` in sequence.
It uses a fake HTTP opener with an in-memory Telegram-shaped reply. No token
is valid, no external HTTP request occurs, and no market price is obtained.
It tests a completed synthetic candle, a horizon-3 prospective forecast,
queueing, one irrevocable claim, exact provider text echo, self-attested ACK,
and blocked duplicate claim/ACK. Failure paths cover ambiguous echo,
network timeout, crash/restart after claim, expiry and a missing-candle gap
before or after claim.

The test intentionally does **not** activate a worker or wire the sender into
production. A successful fake response proves only contract compatibility;
even a real Telegram success response would show provider acceptance, not
recipient/device delivery or human reading. Claims stay
`IN_FLIGHT_UNCERTAIN` after ambiguous outcomes and cannot be blindly
retried. `ACK_RECORDED_UNVERIFIED` is self-attested.

## Remaining activation gates

1. Loop 1: independently authenticated, entitled prospective completed-candle
   observations with provider/venue/side identity, server-owned timestamps,
   expected-bar inventory, session/gap/freshness evidence, and source audit.
2. Loop 5: recipient opt-in, scoped secret storage, authenticated caller
   authorization, durable pre-send attempt metadata, crash/concurrency
   acceptance, manual reconciliation of uncertain sends and monitoring.
3. Release: full exact-head CI, verified restorable production backup,
   rollback rehearsal, safe deployment and post-release health.
4. Trading: independent executable BID/ASK and risk/ledger evidence.
   Historical BID candles and synthetic tests are **not** broker quotes,
   fills, calibrated probabilities or proof of positive returns.

No paper/live orders, broker connections, notification sends, database
migrations or production routes are introduced by this test. Live order
submission always requires explicit owner confirmation of each order,
eligible supported account, fresh executable quote and hard risk limits.
