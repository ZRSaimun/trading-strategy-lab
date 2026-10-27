# Detached signed witness verification for declared M1 receipts

`backend/app/declared_m1_receipt_signed_witness.py` adds an **offline,
read-only Ed25519 signature check** before the existing M1 SQLite journal and
off-journal anchor audit. It does not create or manage keys, request market
data, establish data rights, connect brokers, submit orders or alter a journal.

## API

```python
audit_signed_declared_m1_receipt_anchor_evidence(
    db_path, compiled_manifest, envelope, evaluation_as_of_utc,
    trusted_public_key_hex, trusted_public_key_sha256,
)
```

`envelope` contains exactly `payload` and `signature_hex`. The payload
contains exactly `protocol`, `scope_key`, `issued_at_utc` and `anchors`.
The protocol is `declared-m1-receipt-signed-witness-v1`. Each anchor uses
the exact fields documented in
[the underlying off-journal anchor audit](declared-m1-receipt-anchor-audit.md).
Use 1–16 anchors, a positive UTC issued time not before any witnessed time,
and an evaluation cutoff at or after issuance. Sign the following **exact
bytes** with a separately controlled Ed25519 private key:

```python
message = (
    b"trading-strategy-lab:declared-m1-receipt-witness:v1\n"
    + json.dumps(payload, sort_keys=True, separators=(",", ":"),
                 ensure_ascii=True, allow_nan=False).encode("ascii")
)
```

The `\n` above denotes a single LF byte (not two literal backslash
characters). `signature_hex` is the lowercase 128-character hex signature.
`trusted_public_key_hex` is a 32-byte raw Ed25519 public key encoded as
64 lowercase hex characters. `trusted_public_key_sha256` is the lowercase
SHA-256 hex digest of those 32 raw public-key bytes. The operator **must pin
and distribute both values independently of the supplied envelope**.

For deployments that also require a verified witness *name*, supply the
optional keyword `trusted_witness_id="operator-pinned-witness"`. This must
come from a separately controlled configuration, not from the signed payload.
The verifier then requires **every** signed anchor's `witness_id` to equal
that independently pinned identifier. The identifier must be 1–80 ASCII
letters, digits, periods, underscores, colons or hyphens. Wrong, malformed,
or mixed witness identities fail closed even when the Ed25519 signature is
valid. Without the optional pin, `witness_id_matched_operator_pin=false`;
with a matching pin it is `true`. This is only a local identity-consistency
check, **not** authentication of external witness custody or a trusted clock. Do not
read the trusted key from the same mutable data source as the witness claims.
Do not store a private signing key in the repo, database, logs or application
environment. Key rotation requires an explicit independent trust review.

The verifier rejects invalid signatures, wrong key fingerprints, wrong
scope, malformed payloads, future/retroactive witness issuance, oversized
claims and journal mismatches. An older valid signed anchor does not make a
newer local head valid: the result remains
`HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED`.

**Interpretation:** A valid signature proves possession of the private key
corresponding to the caller-supplied public key, not independent custody,
source authenticity, vendor licensing, trusted wall-clock time, an immutable
external witness, executable BID/ASK or market freshness. All reports keep
`external_witness_authenticated=false`,
`independent_custody_verified=false`, `live=false` and
`may_execute_order=false`. Signature success must not override a HOLD or
be used to activate production trading.

## Synthetic verification

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_declared_m1_receipt_signed_witness.py
```

Tests use ephemeral Ed25519 keys and synthetic historical receipts only.
Production remains blocked by independently controlled immutable witness
custody, authenticated and licensed prospective data, server-owned clocks,
backup restoration, rollback rehearsal and verified health checks.
