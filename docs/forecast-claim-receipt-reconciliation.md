# Forecast claim/outbox/receipt cross-store reconciliation (offline)

`app.forecast_claim_receipt_reconciliation.reconcile_forecast_claim_receipts`
cross-checks a bounded, caller-declared snapshot of decoded durable forecast
alert states with declared one-attempt claims and self-attested Telegram-shaped
transport acceptance records. This closes a gap where a valid claim/receipt
pair could disagree with the **persisted outbox** without detection.

The function is **pure and disconnected**. It does not read or mutate a
database, call Telegram, issue forecasts, authenticate market data, retry a
send, simulate paper fills or submit broker orders.

For each claimed outbox row it requires exactly one claim with the same
session/forecast, claim ID, claim time and expiry. QUEUED/CANCELLED rows must
not have claims. It reuses the strict outbox-health and delivery-acceptance
audits to reject duplicate or malformed records. It identifies an ACK without
a corresponding recorded accepted transport result, acceptance without a
persisted ACK, and unresolved uncertain claims. These conditions require
operator review; **none** permit an automatic retry.

The returned status `SELF_ATTESTED_CROSS_STORE_ONLY` means only that
caller-declared records agree. It does **not** establish independent
population completeness, provider acceptance, recipient/device delivery,
human reading, prospective market-source authenticity, or trading
profitability. `NO_CLAIMED_ALERTS` is not a green delivery signal. The
function intentionally never returns recipient IDs, claim IDs or message
bodies. A claim's recipient ID is not independently anchored in the current
outbox schema; recipient authorization must be verified elsewhere.

Use only after obtaining an appropriately consistent database snapshot
and independent inventory. A later concurrent write can invalidate an
earlier snapshot. A complete production solution additionally requires
authenticated, entitled completed-candle receipts, trusted timestamps,
session-aware expected-bar inventory, durable capture of each one-attempt
transport result, external delivery reconciliation and verified deployment
backup/rollback/health. Historical BID-only candles are **not** live
executable BID/ASK quotes.

All accompanying tests use synthetic records. No live notifications,
paper fills, broker orders, forward returns, drawdown or trading edge
are established.
