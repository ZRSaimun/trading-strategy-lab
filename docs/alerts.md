# Conditional research alerts (v0.4)

Open Research Alerts to save a rule. Select its exact instrument and timeframe in Charts, start historical replay and reveal new candles. Matching observations appear in an in-app banner and persisted event history. Initial chart loading does not backfill events; stepping backward does not trigger an event. Batched forward steps evaluate every newly revealed candle in order.

This is **historical replay only**, not a live-data alert service. The tab must stay open. There is no remote price feed, background worker, scheduled polling, phone push, email or broker integration. Every event says HISTORICAL REPLAY, live=false, quoteTimestamp=null and execution=NONE. No alert arrival before a market move is promised.

## Rules

- CLOSE ABOVE / CLOSE BELOW: previous close must be on the opposite/equal side of the configured level, followed by 1–10 consecutive completed closes strictly across it. The event is observed only at the last accepting candle's close boundary. It is WATCHING LEVEL, never DEMO BUY/SELL CONFIRMED. This is acceptance evidence, not a complete breakout strategy.
- SELL-SIDE SWEEP / BUY-SIDE SWEEP: use the existing two-left/two-right confirmed swing detector with same-bar wick breach and closing reclaim. The event says SWEEP DETECTED. Confirmation timestamps come from candle close, not its open.
- BULLISH FVG / BEARISH FVG: use the three-candle non-overlapping wick detector. The event says PATTERN OBSERVED. Mitigation or defended retest is not inferred.

The relevant source candles must be complete aggregates with all expected one-minute constituents and contiguous timestamps. Pattern detection discards earlier history across a missing-minute or partial-bar boundary. Missing/invalid source metadata, wrong instrument/timeframe and paused rules cannot trigger. Weekly/monthly rules are not available. Daily rules currently require a complete 24-hour UTC dataset, so exchange-session daily coverage is not assumed valid.

Observed events include exact instrument, timeframe, rule ID/version, original CSV SHA-256, source, evidence candle opens, observed close boundary, historical close, pattern/price level, cancellation explanation and unavailable-news label. No entry, stop, target or net RR is manufactured; the full demo confirmation engine remains pending.

## Persistence and audit

Rules can be paused and re-enabled. Each change increments the rule version. Event IDs include rule ID, version, full dataset hash and observed candle open. A retained event is not emitted again on rewind/replay or refresh; replacing the dataset or revising a rule gives a distinct identity. Sequential repeated event writes are idempotent and preserve the original event. Authenticated private-server writes and browser-local writes generate audit records.

Browser mode retains the newest 100 rules and 500 events, and its usual 200-record audit window. Export rules/events as JSON for longer retention. Deduplication applies to retained events; evicted events can reappear in later replays. Records are not a backup. Private-server storage uses the owner session and database. Client-generated events are unverified research records, not independent server market observations. Multi-tab and concurrent-write coordination are not yet implemented; edit/replay in a single tab. Deletion, full rule editing and JSON restore UI are future tasks; pause an unwanted rule.

## Tests and remaining work

Seven deterministic alert tests cover acceptance timing, event identity/deduplication, disabled/mismatched/missing data, partial aggregates and gaps, FVG close timing, gap-isolated swings, schema bounds and batched replay advances. A backend test verifies authentication, sequential idempotency and one audit entry for repeated event submission. Together with prior suites: 21 frontend tests and 8 backend tests.

Browser end-to-end interactions remain unverified. Live candle-close processing, executable quote freshness, server alert workers, delivery channels, macro conflicts, complete entry/stop/target candidates and authenticated AI/MCP access still need implementation and an authorized feed/private deployment.
