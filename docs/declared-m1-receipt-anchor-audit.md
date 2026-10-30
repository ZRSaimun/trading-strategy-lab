# Offline M1 receipt off-journal anchor claim audit

`backend/app/declared_m1_receipt_anchor_audit.py` compares the **already
revalidated** local SQLite receipt journal with a bounded list of separately
retained, caller-supplied checkpoint claims. It makes no provider, broker,
network, subscription or production writes and does not activate a feed.

## Use

`audit_declared_m1_receipt_anchor_evidence(db_path, manifest, anchors, evaluation_as_of_utc)`

`manifest` is the existing compiled ExpectedM1Manifest for the same
provider/instrument/venue/price-side/calendar scope. `anchors` is an ascending
list of 1–16 dicts, each with exactly:

- `scope_key`: SHA-256 scope key of the journal's declared identity.
- `revision`: positive journal revision.
- `checkpoint_sha256`, `previous_checkpoint_sha256`: lowercase 64-digit SHA-256.
- `declared_observed_at_utc`: integer observed timestamp of the stored manifest.
- `witnessed_at_utc`: separately recorded integer UTC witness timestamp,
  not earlier than the declared observation and not after the evaluation cutoff.
- `witness_id`: 1–80 safe identifier characters.
- `evidence_ref`: unique 1–160-character off-journal reference.

Supply only claims obtained from a **separately controlled, immutable witness**.
This library cannot verify custody, signature, identity, trusted clock, vendor
authenticity or whether an evidence reference exists. Do not generate an anchor
from the same journal and treat the resulting self-consistency as independent
evidence. Witness custody/signatures and source licensing must be verified by
a separate, authorized process.

The audit rechecks the entire local chain, exact anchored revision and previous
hash, declared scope, nondecreasing observation/witness chronology, distinct
evidence references and the evaluation cutoff. If the local head is newer than
the last supplied anchor, the result is
`HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED`. A consistent rollback that removes
an anchored revision fails closed. It cannot detect an attack where the witness
claims are forged or replaced together with the database.

All outputs retain `external_witness_authenticated=false`,
`independent_custody_verified=false`, `live=false` and
`may_execute_order=false`. The source is caller-declared; there is no verified
market calendar, price freshness, completed-candle entitlement, executable
spread or authenticated server receipt timestamp. Do not use the audit result
to authorize market analysis, signals, broker orders or a production release.

## Synthetic tests

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_declared_m1_receipt_anchor_audit.py
```

This is an opt-in offline component. Keep PR #65 draft and undeployed until
exact-head CI, authenticated and licensed feed acceptance, independently
anchored server-owned clocks, verified backup restoration, rollback rehearsal
and health checks are complete.
