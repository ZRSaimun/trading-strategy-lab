# Declared off-journal demo receipt checkpoint comparison (Loop 3)

This **read-only, opt-in research audit** compares a local SQLite demo-order
receipt history with **caller-supplied records allegedly retained outside the
journal**. It does **not** create, upload, sign, authenticate, or independently
retain any record. A matching hash is not proof of broker fills, external
custody, correct event population, or profitability.

```python
from app.offline_demo_receipt_anchor_audit import (
    audit_declared_demo_receipt_anchor_evidence,
)

result = audit_declared_demo_receipt_anchor_evidence(
    "/private/local/declared-demo-receipts.sqlite",
    order_scope,
    [{
        "revision": 1,
        "checkpoint_sha256": committed_head_sha256,
        "previous_checkpoint_sha256": "0" * 64,
        "as_of_ms": 200,
        "witnessed_at_ms": 250,
        "witness_id": "offline-vault",
        "evidence_ref": "vault/checkpoint-1",
    }],
    evaluation_as_of_ms=300,
)
```

The example times are synthetic epoch milliseconds, not actual market times.
The audit validates the entire stored receipt history before comparing up to
32 ascending anchored revisions. It checks immutable order identity, SHA-256
links, declared snapshot cutoffs, witness chronology, duplicate evidence refs,
missing revisions and any unanchored later local head. It never modifies the
SQLite journal. An unanchored newer head yields
`HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED`, not an approval.

## Independent custody and release limits

To provide actual independent evidence, an operator must retain checkpoints in
an access-controlled **separate trust domain**, with authenticated timestamps,
immutable retention and verifiable signatures or trusted attestations. Those
capabilities are **not implemented** here. A malicious actor controlling both
SQLite and the supplied anchors can rewrite them consistently. Witness IDs and
evidence references are opaque caller assertions, not validated external URLs.

No broker adapter, network call, account credentials, order placement, live
execution, demo order execution, licensed archive handling, schema migration,
production deployment or spending is introduced. Every result reports broker
population and witness authentication as **false** and both execution flags as
**false**. Actual CFD financing, executable spreads, slippage, account
settlement, broker receipts and frozen multi-year holdout performance still
require separate independently sourced research.

If the local chain or an anchor disagrees, quarantine and investigate; do not
rewrite history or regenerate purportedly independent checkpoints. This module
is not a substitute for tested backup/restore and release rollback procedures.
