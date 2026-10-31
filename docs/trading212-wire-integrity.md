# Trading 212 read-only wire-integrity hardening

This is an extension of the optional disconnected read-only Invest/Stocks ISA
adapter in docs/trading212-readonly.md. No account or feed is connected.

## Fail-closed response handling

- Explicitly request identity-encoded JSON. Reject Content-Encoding values other
  than identity; do not transparently decompress provider responses. Read real
  streamed responses as raw wire bytes in bounded 64 KiB chunks and enforce the
  existing 8 MiB cap before JSON parsing. A test-only MockTransport can return
  already-buffered Response objects.
- Reject duplicate JSON object keys at every nesting level instead of silently
  accepting the last value.
- Reject NaN, Infinity and floating-point overflow to non-finite values.
- Keep response-body and credential details out of raised error messages.
- Keep GET allowlist, declared eligible account types, fixed TLS origins, no
  redirects/proxies, no persistence, no retries, and no order capabilities.

These safeguards protect downstream interpretation of broker metadata and
account snapshots. They do not authenticate instrument identifiers, verify the
provider clock, attest prices, prove data licensing, or supply CFD quotes.
A provider that requires compression must be separately reviewed before any
policy change; do not silently enable decompression.

## Reproducible isolated verification

Run from backend with httpx 0.28.1 and pytest installed:

    PYTHONPATH=. pytest -q tests/test_trading212_readonly.py tests/test_trading212_json_integrity.py

All tests use synthetic HTTPX MockTransport responses, with no real credentials,
network, live feeds or broker orders. No production deployment is authorized
by these tests. Preserve draft status until exact-head CI, main reconciliation,
and owner-host backup/restore/rollback/health checks are verified.

Official API scope rechecked 26 Oct 2026: https://docs.trading212.com/api
The API is documented for Invest and Stocks ISA, not CFDs.
