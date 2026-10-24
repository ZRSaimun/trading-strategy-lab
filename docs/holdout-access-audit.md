# Offline holdout commitment and access receipts (Loop 3)

This **disconnected, research-only** primitive adds `frontend/lib/holdout-access-audit.ts` alongside the source-isolated purged holdout planner. It does not read prices, labels, P&L, market data, broker records or trading orders; it has no network, storage, UI, broker adapter or real-money execution path.

## Intended procedure

1. Independently verify authorized archive bytes and SHA-256 hashes, source identity, UTC conventions, licenses, label availability and evaluation dates. Predeclare the strategy version, frozen configuration digest, fixed embargo and chronological boundaries **before** inspecting holdout outcomes.
2. Call `createHoldoutCommitment(archives, protocol, operatorId, frozenAt)`. The module validates the existing partition protocol and source lineage, canonicalizes the archive order, and SHA-256-hashes the complete declared commitment. `frozenAt` is caller-supplied and must strictly precede the validation start (`developmentEnd`). **It is not a trusted clock or external preregistration.**
3. Independently timestamp and externally anchor the commitment digest in access-controlled, append-only storage. Record every validation/holdout access and holdout evaluation using `appendHoldoutAuditEvent`. Persist the returned array with an atomic compare-and-swap transaction; externally anchor each new chain head. This module **does not** provide atomic persistence, a lock, access enforcement or a trusted log.
4. Call `verifyHoldoutAudit` before interpreting a holdout. It rejects missing/reordered links, changed event fields, duplicate IDs, backwards timestamps, unknown archives, extra outcome fields and altered commitments. Recorded validation access before `developmentEnd`, holdout access before `validationEnd`, or protocol revision is flagged `CONTAMINATION_RECORDED`.
5. Do not interpret `NO_CONTAMINATION_RECORDED` as proof of an untouched sample. Accesses may have been omitted; an operator can rewrite an unanchored chain and forge timestamps. Independent access controls, trusted timestamps, immutable logs and independent review remain mandatory.

No realized outcomes, prices or freeform event notes are accepted. The event types are `VALIDATION_ACCESS`, `HOLDOUT_ACCESS`, `HOLDOUT_EVALUATION` and `PROTOCOL_CHANGED`. A recorded protocol revision contaminates the original frozen protocol; create a separate preregistered study rather than retroactively changing its evaluation rules.

## Tests and limitations

`cd frontend && node --experimental-strip-types --test tests/holdout-access-audit.test.ts`

Eleven synthetic tests cover five-year source lineage, canonical commitment digests, append-only chain structure, tamper detection, omitted/reordered entries, duplicate/backdated events, invalid source IDs, outcome-field rejection, early holdout access, protocol revision and explicit limitations. No market or broker results are measured.

This is not proof of profitable trading, a statistically independent untouched holdout, real CFD bid/ask execution, slippage, financing or margin. A complete research workflow still requires externally authenticated archive digests, independent audit anchoring, realistic source-specific costs, actual authorized demo-fill comparisons, isolated test databases, and independently reviewed holdout policies.

No production deployment or merge should occur until the latest-head full CI passes and the exact production backup, rollback and health-check readiness are verified. Production may auto-deploy on merge.

## Validation-start leakage guard (24 October 2026)

A commitment asserted at or after `developmentEnd` now fails closed at creation and during digest revalidation. An audit event recording validation access before `developmentEnd` contaminates the original frozen study, even if the hash chain and signatures are otherwise valid. This is a stricter protocol requirement than merely freezing before holdout starts. Older commitments frozen during validation require a newly preregistered forward study; never backdate or relabel a previously inspected period. Two synthetic regression cases exercise the freeze cutoff and early validation read. Caller timestamps remain self-attested until independently verified.
