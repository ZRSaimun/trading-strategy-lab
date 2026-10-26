# Persisted paper quote-marker integrity hardening (Loop 4)

This change tightens `PaperQuoteReplayStore._decode`, which is shared by the standalone quote marker and atomic quote+journal checkpoint code.

## New fail-closed invariants

- The stored version must be the integer `1`, not JSON `true`.
- `observed_at_ms <= received_at_ms <= accepted_at_ms` must hold.
- A persisted accepted marker must be no older than the maximum 60-second quote-age policy at acceptance. This is a **historical structural bound**, not permission to accept 60-second quotes for trading.
- The marker revision cannot exceed its strictly increasing quote sequence.
- The unique recent quote-ID hash history must contain exactly `min(revision + 1, 64)` entries. A shorter history cannot silently forget recently observed identifiers.
- Stored envelope size is checked in UTF-8 bytes before JSON parsing.

The new synthetic tests deliberately recompute the record's non-authenticating SHA-256 checksum after corrupting its fields, then verify that both load and subsequent observation reject the record without advancing its state or writing an additional audit entry. A valid 67-quote sliding window remains loadable.

## Safety and integration limits

This is **not** a broker-feed signature, authoritative quote authentication, trading-session calendar, execution gate, or evidence of an executable price. Existing `ACCEPTED_UNVERIFIED` means only that a paper replay marker was recorded. It never authorizes paper or live orders. No broker connector, credential, endpoint, migration, production data rewrite, paid service or live trading is introduced.

Corrupt existing records require offline manual reconciliation; do not automatically reset markers or reuse order IDs. Before any future execution path, require provider-authenticated, monotonic quotes, transactional risk reservations, actual stop acknowledgements, broker inventory/fill reconciliation, owner-per-order approval for live trades, and tested crash recovery. Trading 212's documented public API does not provide CFD order execution.

## Deployment handoff

The repository's `render.yaml` contains `autoDeployTrigger: checksPass`. Do not merge until the actual production service's auto-deploy configuration, owner-confirmed workspace, restorable backup, rollback method and post-deployment health checks are independently verified. A green CI run alone is insufficient for deployment.
