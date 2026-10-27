# External checkpoint fence for the paper submission ledger

`backend/app/paper_submission_anchor_fence.py` is a disconnected, read-only
comparison layer for the SQLite submission ledger in PR #148. It calls the
existing full ledger audit and checks the current event count, chain tip,
order count and canonical order projection against an **exact** externally
trusted checkpoint. A changed ledger (including legitimate new events) fails
closed until a new checkpoint is independently verified.

The caller must obtain and authenticate the checkpoint through an independent
trust channel, store it outside the SQLite database and its backup set, and
provide a trusted clock. The helper **does not** authenticate the checkpoint,
verify signatures, provide external storage, detect a maliciously forged
checkpoint, prove the broker's actual state, or authorize any trading. A
self-generated or ledger-co-located checkpoint is not independent evidence.

`verify_external_anchor(path, anchor=..., now_ms=..., max_age_ms=300000)`
requires exactly `schema`, `event_count`, `order_count`, `audit_tip_sha256`,
`order_projection_sha256`, and `recorded_at_ms`. Default freshness is five
minutes, with a hard maximum of 24 hours. All results remain
`HOLD_RECONCILIATION`, `may_submit_paper_order=False`, and
`may_submit_real_order=False`. No network, credentials, broker submission,
paid resources, database migration or production write is introduced.

This is an additive defense against unnoticed local ledger rollback. It is
not a replacement for authenticated broker reconciliation, one-time signed
owner approval, atomic risk reservations, or recovery/rollback verification.
