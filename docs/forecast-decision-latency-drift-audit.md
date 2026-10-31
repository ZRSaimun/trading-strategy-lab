# Offline chronological decision-latency drift audit

`audit_forecast_decision_latency_drift` compares declared post-close decision
latencies in the first and last chronological halves of each model-version and
forecast-horizon cohort (1, 3 or 12 completed candles).

The full declared forecast/abstention census must reconcile exactly before any
latency percentiles are published. Missing, contradictory, duplicate, unexpected,
or invalid decisions withhold **all** group metrics. Each half requires at least
30 decisions; p95 uses nearest rank, and the default descriptive warning is a
strict increase greater than 10 seconds. The separate default late-decision
threshold is 15 seconds after candle close. Warning thresholds are not
statistical significance tests.

Source identity, expected schedule, decision clocks, abstentions, and receipts
remain caller-declared, **not independently authenticated**. The audit does not
connect to a market feed, enable alerts, demonstrate recipient delivery, generate
paper fills, submit orders, or prove profitability. Historical BID candles are
not executable quotes.

Loop 1 handoff: provide independently registered model/horizon expected-bar
schedules, authenticated completed-candle receipts, source/side/session lineage,
trusted server-owned UTC receipt timestamps, and independently reconciled missing
issuance/abstention evidence. Do not promote this audit to live trading or
production alert permissions without those prerequisites and release gates.
