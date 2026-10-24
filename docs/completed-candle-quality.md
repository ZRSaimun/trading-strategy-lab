# Completed-candle receipt and observed gap audit (Loop 1)

The private Twelve Data **manual historical import** records a bounded, read-only `quality` object alongside its existing provider-specific manifest. The source remains `XAUUSD-TD` / `XAU/USD` at 1-minute UTC resolution. The audit never changes, synthesizes, interpolates or submits a candle and never calls a vendor itself.

`observed_at_utc` is the backend's evaluation time, not a provider-signed quote timestamp. `last_candle_close_utc` is the last accepted candle's UTC minute-end. `seconds_since_last_candle_close` is a descriptive historical age; **it does not classify the source as live or stale relative to a market session**, because no authorized market calendar or feed-delivery SLA has been verified. `observed_timestamp_gaps` counts jumps larger than one minute. `unobserved_minutes_between_candles` and bounded `gap_samples` describe those jumps; weekend/session closures and outages are indistinguishable without a verified trading calendar.

`market_calendar_checked`, `source_authenticity_verified`, `provider_entitlement_verified`, `executable_bid_ask_verified`, `live` and `may_execute_order` remain `false`. A SHA-256 of the vetted source-field snapshot is not a signed vendor statement. Historical BID/mid OHLC bars are not an executable two-sided CFD quote or broker spread.

The audit fails closed on malformed, non-UTC-minute, duplicate, out-of-order, incomplete or future timestamps. It also rejects nonnumeric, NaN, infinite or internally inconsistent OHLC values, and invalid optional volume. `ohlc_invariants_checked=true` means only that numeric bar invariants were checked; it does **not** prove a vendor source, correct venue, price side or executable quote. `price_side=UNVERIFIED` remains explicit. It uses only the already normalized completed-candle rows and a server-owned timestamp; no provider credentials are read by the auditor. Existing `gaps` and manifest fields remain unchanged for backwards compatibility. No database migration or new route is introduced.

## Tests and operational limits

Run `cd backend && PYTHONPATH=. pytest -q tests/test_completed_candle_quality.py tests/test_provider.py`. Tests use synthetic timestamps and a mocked provider. Real feed access, provider entitlement, quote authenticity, expected trading hours, account-level licensing, delays, actual spread and order execution **are not verified**.

Before a future authenticated completed-candle feed can be advertised as current, obtain the exact authorized provider/venue/instrument, exchange or broker timestamp semantics, feed-delay/closure calendar, contractual display/non-display rights, server receipt clock and monotonic append-only provenance. Preserve raw response evidence only when licensing and security permit. Never infer CFD API availability from an equity API.

Trading 212 official API scope (rechecked 2026-10-24): https://docs.trading212.com/api — Invest and Stocks ISA only, not CFD.
