# Loop 5 — Disconnected Telegram forecast-review transport

This change adds backend/app/forecast_telegram_transport.py as a narrowly scoped, opt-in one-attempt Telegram Bot API transport. It is not imported by the application and has no scheduler, route, credentials, worker, webhook, notification channel or broker/order path. Importing it makes no network calls. No actual notification has been sent.

## Operational contract

Before calling, a future authorized worker must independently verify user and recipient opt-in, account authorization, an entitled and authenticated prospective completed-candle source, exact feed identity and price side, server-owned receipt timestamps, unexpired forecast, and a durable one-time ForecastAlertOutbox claim. It must persist attempt metadata before sending. Timeout, malformed/mismatched response, redirect, process crash or ambiguous provider response leaves the claim IN_FLIGHT_UNCERTAIN. **Never automatically retry an uncertain attempt:** Telegram may already have accepted the request. A successful Bot API sendMessage response proves at most provider acceptance, not device delivery or human reading. Existing ACK_RECORDED_UNVERIFIED remains unverified. Keep tokens in secret storage and never log URLs, raw exceptions, response bodies or message text.

The adapter uses the official Telegram Bot API HTTPS sendMessage endpoint with fixed api.telegram.org host, strict token/chat-ID validation, JSON POST, 1–10-second timeout, disabled redirects, 16-KiB response cap, duplicate-key rejection, exact recipient ID and positive integer message ID validation. No internal retry, arbitrary destination URL or order capability. Source authentication and provider entitlement are NOT established by this module.

## Verification

Run from backend: PYTHONPATH=. pytest -q tests/test_forecast_telegram_transport.py

22 isolated deterministic synthetic tests cover accepted response without delivery proof, malformed/oversized/mismatched replies, duplicate keys, network failures, timeout-like errors, argument bounds and redacted exceptions. Injected fake HTTP opener means **zero actual network requests**. These tests do not demonstrate real provider delivery or production uptime.

## Activation gates and handoffs

Do not connect or deploy this sender until legitimate Telegram bot and opted-in recipient, securely scoped secrets, independently authenticated prospective source receipts, source/session/gap checks, durable claim/reconciliation worker, concurrency and process-crash acceptance, full latest-head CI, restorable backup, rollback and post-release health are verified. Historical BID and replay observations are never live executable broker quotes. No measured forward returns, drawdown or profitable edge.

**Loop 1:** Provide licensed/authenticated completed-candle receipts, trusted server clocks, expected-bar and session register, exact provider/venue/side identity and stale/gap rejection. **Loop 4:** Broker risk, demo fill reconciliation and owner-specific real-order approval are separate; this transport can never place orders.

## Malformed-response and uncertain-outcome hardening (26 October 2026)

The single-attempt adapter now maps incomplete HTTP response reads, HTTP framing errors, decoder recursion failures, and malformed injected HTTP response objects to a sanitized `DeliveryUncertain` exception. An HTTP failure can occur after the provider accepted a send: **do not automatically retry** an uncertain claim. Never log raw HTTP exception bodies, token-bearing request URLs or response text. This hardening does not authenticate market observations, establish provider delivery or authorize any send.

Five additional isolated synthetic cases bring the transport suite to **27 passing tests locally** on Python 3.13. Tests use fake openers and zero network calls. Full latest-head GitHub CI is required before considering any integration; no production deployment, credential configuration, broker order or notification was performed.
