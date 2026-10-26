# Loop 4 — disconnected paper exit-bracket inventory review

`backend/app/paper_bracket_exit_guard.py` reviews one **caller-declared** open
position and a bounded, supposedly complete exit-order inventory. It performs
no API calls, DB writes, broker authentication, order placement or cancellation.

It checks source/account/position identity, unique order IDs, correct opposite
exit side, declared reduce-only flags, exactly one acknowledged stop with
exactly the open position quantity, optional matching OCO target, no unresolved
cancel/replace/submission, partial-fill quarantine, bounded recent inventory
snapshot, valid acknowledgements, and exact Decimal stressed-loss cap.

**Critical boundary:** A structurally consistent declared bracket is not
evidence that the broker actually holds or will honor its stop, reduce-only,
OCO link, fill population or position quantity. Stops may slip or gap, and the
declared stressed exit is not a worst-case guarantee. A stale or incomplete
snapshot cannot be used to certify risk. Every result is
`HOLD_RECONCILIATION` with paper and real-money execution disabled.
`review_sha256` is an unkeyed review fingerprint, **not** a broker signature.

Synthetic tests:
```sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_paper_bracket_exit_guard.py
```

Before integrating any provider: independently authenticate complete broker
positions, working orders and executions; verify actual supported order types,
OCO/reduce-only semantics and cancel/replace acknowledgement; persist quote,
inventory and risk-reservation checkpoints atomically; quarantine ambiguous
network outcomes without retries; require per-order positive owner approval for
real money. Trading 212's documented Public API supports Invest and Stocks ISA,
not CFDs (https://docs.trading212.com/api/section/general-information/api-limitations).
