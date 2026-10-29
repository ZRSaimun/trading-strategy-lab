# Disconnected credit-ledger integrity preflight (Loop 1)

`app.provider_credit_ledger_audit.audit_provider_credit_ledger` is a **read-only,
owner-offline** diagnostic for the existing Twelve Data SQLite credit ledger.
It makes **no API calls**, does not change a daily budget, does not reserve or
refund credits, does not authenticate the owner, and cannot enable a live feed
or submit an order. Run it only after stopping all ledger writers and while
using a private, durable, single-host copy with a verified recovery procedure.

It checks the ledger's owner-only file/directory permissions, size bound,
absence of WAL/SHM/rollback-journal sidecars, expected two-table schema,
SQLite integrity and foreign keys, policy identities/evidence-hash shapes,
reservation IDs, manifest digest shapes, reservation UTC-day timestamps,
per-day budget overspend, and any adjacent reservations less than 60
seconds apart, including across UTC minute and midnight boundaries. This
rolling cooldown matches the live one-shot reservation gate; a new UTC
minute does not reset it. The check is an offline consistency invariant,
not an independently verified vendor quota. Existing ledgers with
historical violations will fail this audit until separately investigated;
never silently rewrite historical reservations. The entire ledger is SHA-256 fingerprinted before
and after the audit, and any mismatch is rejected. It returns only aggregate
counts and a file digest; no keys, request IDs or evidence references.

Example on a **synthetic, quiescent development ledger only**:

```python
from app.provider_credit_ledger_audit import audit_provider_credit_ledger
report = audit_provider_credit_ledger(
    "/absolute/private/durable/provider-credits.sqlite", utc_day="2026-10-26"
)
assert report["provider_entitlement_verified"] is False
```

`CONSISTENT_OFFLINE_ONLY` means only that this local snapshot passed the
specified checks. `NO_POLICY_FOR_DAY` is not permission to make a request.
Neither result is provider-billing reconciliation, proof of API-key ownership,
verified licensing, authenticated source identity, market-data freshness,
market-calendar validation, or authority to activate a feed or execute orders.

**Limitations:** The owner must quiesce writers first. Immutable read-only
SQLite inspection intentionally rejects journal sidecars; it must never ignore
uncheckpointed WAL writes. File hashing cannot prove there was no transient
write or hostile race during the scan. OS ACLs, all ancestor paths, filesystem
snapshots and backup restoration are not independently verified. SQLite
integrity checks are not a substitute for an independent vendor invoice/usage
statement. No automatic polling or deployment is introduced.

Synthetic tests: `cd backend && PYTHONPATH=. pytest -q tests/test_provider_credit_ledger_audit.py`.

## Rolling 60-second audit parity (29 October 2026)

The original offline audit rejected only two reservations in the **same
calendar minute**. It could incorrectly report a clean ledger for two
reservations at `08:00:59` and `08:01:00`, despite the active reservation
gate enforcing a rolling 60-second cooldown. The audit now sorts all
reservations by timestamp and rejects any adjacent pair less than 60 seconds
apart, including when their UTC days and daily policies differ. Exactly
60 seconds is permitted. The audit does not mutate historical entries or
refund credits.

Synthetic, offline regressions cover 1-, 30- and 59-second minute-boundary
gaps, an exact 60-second allowance, and 1-, 59- and 60-second midnight
transitions. These checks prove local policy consistency only, not provider
quota consumption, entitlement, source authentication or account-wide
reconciliation. No paid request or market-data activation is involved.
