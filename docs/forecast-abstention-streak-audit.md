# Declared forecast abstention streak audit (offline)

`audit_forecast_abstention_streaks(snapshot, expected_identity, expected_keys, abstentions, as_of=...)` in `backend/app/forecast_abstention_streak_audit.py` is a **read-only, disconnected** operator diagnostic. It does not run a forecasting model, authenticate market data, send Telegram messages, fill demo trades, or authorize broker orders.

It first requires the existing forecast-or-abstention **decision coverage census** to match every independently declared expected model/version/horizon/base-candle combination exactly once. Missing, unexpected, duplicate or conflicting decisions suppress all streak metrics. The declared schedule and abstentions are not independently witnessed; matching records remain **UNVERIFIED**.

For each model version and horizon (1, 3, 12 candles), it measures the longest consecutive abstention run, longest consecutive same-reason run, and currently trailing runs. Runs require base-candle starts exactly one declared candle duration apart; a weekend/session gap, even when omitted from the expected schedule, breaks the run. This is a *declared schedule* metric, not an authenticated trading-session outage or delivery-latency SLA. The default review threshold is 12 consecutive abstentions and the default minimum complete decision population is 30. Thresholds are operational heuristics, not statistical tests. Ties retain the earliest chronological run.

The report never returns `maySendNotification`, `mayExecutePaperOrder` or `mayExecuteLiveOrder` as true. A clean streak result does **not** establish data rights, completed-candle provenance, forecast skill, forward returns or profitable execution.

**Loop 1 handoff:** independently entitled provider receipts, trusted server-owned UTC candle close/receipt timestamps, authenticated source/side/session calendars, and a separately registered immutable expected decision schedule are still needed. Append-only witnessed abstention reasons are required to turn caller declarations into independent evidence. Keep this audit offline until all such provenance and release/rollback gates are independently verified.
