# Unchanged-source control for future timestamp preflight

`frontend/tests/hourly-fvg-future-source-unchanged-control.test.ts` complements the future source-declaration mutation regressions. A synthetic future hourly timestamp accessor that does **not** mutate the completed source must allow the causal as-of scanner to continue, while future OHLC, volume, and observed-minute accessors remain unread. The completed prefix explicitly declares unverified volume and uses null volume, which must never be promoted to verified evidence.

This guards against a false-positive source-snapshot integrity rejection while preserving the future-data boundary. It is not a real market-data, broker quote, source identity, cost, or profitability validation. Keep the PR draft, paper-only, unmerged and undeployed pending exact-head CI and independent licensed data verification.
