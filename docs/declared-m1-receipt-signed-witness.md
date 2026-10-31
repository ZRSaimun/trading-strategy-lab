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
and distribute both values independently of the supplied envelope**. Do not
read the trusted key from the same mutable data source as the witness claims.
Do not store a private signing key in the repo, database, logs or application
environment. Key rotation requires an explicit independent trust review.

For deployments that also require a verified witness *name*, supply the
optional keyword `trusted_witness_id="operator-pinned-witness"`. This must
come from a separately controlled configuration, not from the signed payload.
The verifier then requires **every** signed anchor's `witness_id` to equal
that independently pinned identifier. The identifier must be 1–80 ASCII
letters, digits, periods, underscores, colons or hyphens. Wrong, malformed,
or mixed witness identities fail closed even when the Ed25519 signature is
valid. Without the optional pin, `witness_id_matched_operator_pin=false`;
with a matching pin it is `true`. This is only a local identity-consistency
check, **not** authentication of external witness custody or a trusted clock.

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

## Optional independently pinned checkpoint floor

A valid older journal **and** a valid older signed envelope can be replayed
together. Signature verification alone cannot discover this rollback if both
objects have been replaced with mutually consistent old copies.

For an operator that has independently retained a trusted minimum checkpoint,
the verifier accepts an optional keyword-only `trusted_floor` dictionary
with **exactly** `scope_key`, `revision`, `checkpoint_sha256` and
`witness_id`. Also supply the independently pinned `trusted_witness_id`,
which must equal the floor's witness ID. For example:

```python
trusted_floor = {
    "scope_key": operator_recorded_scope_key,  # 64 lowercase hex chars
    "revision": operator_recorded_revision,    # positive integer
    "checkpoint_sha256": operator_recorded_checkpoint_sha256,
    "witness_id": "operator-pinned-witness",
}
report = audit_signed_declared_m1_receipt_anchor_evidence(
    db_path, manifest, envelope, evaluation_as_of_utc,
    trusted_public_key_hex, trusted_public_key_sha256,
    trusted_witness_id="operator-pinned-witness",
    trusted_floor=trusted_floor,
)
```

The signed anchor population **must explicitly include** the pinned revision
and its exact checkpoint digest. Otherwise the call fails closed, even when
the older signature and older local journal are internally valid. The
underlying audit still verifies the entire local chain, and a valid older
floor **cannot** turn an unanchored newer local head from HOLD into approval.
The report's `operator_pinned_checkpoint_floor_matched` is `true` only
when a separately supplied floor was checked. Omitting the optional floor
preserves legacy behavior and reports `false`.

The floor is useful **only if its values were captured and retained outside
the mutable local journal and signed-envelope delivery channel**, with
operator-controlled integrity and a documented update process. A floor
copied from the same possibly rolled-back envelope offers no protection.
It is a *minimum*, not a trusted clock, external witness authentication,
provider license, market price validation, or permission to trade.
Because signed anchor populations are limited to 16, a retained floor that
is not present in the submitted signed anchors causes a deliberate rejection;
operators must explicitly advance their independently retained floor rather
than silently skipping it.

## Optional declared witness age policy (not independent freshness)

For an **offline, caller-declared** evaluation-time gate, pass
`max_declared_witness_age_seconds=60` (integer 1–86,400). The verifier
rejects a signed envelope if **either** its `issued_at_utc` **or** the
latest anchor's `witnessed_at_utc` is more than 60 seconds before
`evaluation_as_of_utc`. The latter condition prevents merely re-signing
an old anchor with a newer issuance timestamp to satisfy the policy.
The equality boundary is accepted. Invalid policy values fail closed.

With the option enabled, the report includes
`declared_witness_age_policy_checked=true`,
`declared_witness_issued_age_seconds`, and
`declared_last_anchor_age_seconds`. Without it, the first field is
`false` and both ages are `null`; existing callers remain compatible.
The check never overrides an unanchored-head HOLD.

**Important:** All three times are claims evaluated against the supplied
cutoff, not an independently attested clock. A compromised signing key,
dishonest witness, replayed cutoff, or colluding source can still forge
apparent recency. This is not proof of live data, trusted external custody,
provider authenticity, exchange calendar coverage, licensing, or executable
BID/ASK. The verifier continues to report
`trusted_witness_clock_verified=false`,
`external_witness_authenticated=false`, `live=false`, and
`may_execute_order=false`. Do not use this gate to activate trading.

## Synthetic verification

```sh
cd backend
PYTHONPATH=. pytest -q tests/test_declared_m1_receipt_signed_witness.py
```

Tests use ephemeral Ed25519 keys and synthetic historical receipts only.
Production remains blocked by independently controlled immutable witness
custody, authenticated and licensed prospective data, server-owned clocks,
backup restoration, rollback rehearsal and verified health checks.
