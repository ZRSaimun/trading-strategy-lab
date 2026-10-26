# Forecast delivery acceptance correlation (offline)

`app.forecast_delivery_acceptance_audit.audit_forecast_delivery_acceptances`
correlates **caller-declared** one-time forecast claims with **self-attested**
results returned by the disconnected Telegram transport. This is an isolated
read-only function: no database reads/writes, HTTP requests, retries, alerts,
broker calls or order execution. It is not wired into a production worker.

Inputs are bounded to 1,000 claims and 1,000 receipts. Each claim declares a
session, forecast, 32-character lowercase claim token, numeric recipient ID,
claim time and expiry. Each receipt binds to exactly one claim, includes a
server-recorded timestamp and the exact conservative `send_telegram_once`
return shape. Duplicate claims, duplicate receipts, reused chat-scoped Telegram
message IDs, mismatched recipients, malformed booleans and impossible clocks
fail closed. Missing receipts are **uncertain**, including after expiry, and
are never automatically retried. Receipts recorded at/after expiry require
operator review; the recorded time is **not** proof of when Telegram sent or
delivered a message.

Example (synthetic data only):

```python
from app.forecast_delivery_acceptance_audit import audit_forecast_delivery_acceptances

report = audit_forecast_delivery_acceptances(
    claims=[{"sessionId": "synthetic_session", "forecastId": "synthetic_forecast",
             "claimId": "a" * 32, "recipientId": "-1001234567890",
             "claimedAt": 130, "expiresAt": 180}],
    receipts=[],
    as_of=150,
)
assert report["status"] == "OPERATOR_REVIEW_REQUIRED"
assert report["retryPermitted"] is False
```

This audit **does not independently verify provider acceptance, Telegram
delivery, device receipt or human reading**. Even a matching result is
`SELF_ATTESTED_ACCEPTANCE_ONLY`. Do not publish claim IDs, recipient IDs,
tokens or raw message bodies. Production activation requires authenticated
prospective completed-candle receipts, entitled market data, owner-authorized
recipients, durable server-side claim/result capture, external reconciliation
and proven rollback/health gates. Historical BID candles cannot stand in for
executable BID/ASK quotes. No measured forward calibration, trading returns,
drawdown or profitability are established by these synthetic tests.
