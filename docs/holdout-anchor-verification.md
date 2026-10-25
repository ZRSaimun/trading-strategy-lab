# Offline holdout anchor-head comparison (Loop 3)

`frontend/lib/holdout-anchor-verification.ts` compares an already verified, source-identified holdout access audit to independently retained external anchor receipts. It **does not** contact or authenticate any third-party timestamping service. The supplied receipt's `authority`, `reference`, and `anchoredAt` are assertions until verified out of band. A matching receipt is **not** proof of an untouched holdout or of actual market returns.

## Safe workflow

1. Validate archive SHA-256 against authorized raw source bytes and verify source, licensing, calendar and label availability independently. Freeze the research protocol **before** holdout access.
2. Call `verifyHoldoutAudit(commitment, entries)` from `holdout-access-audit.ts` first. Reject errors and contamination findings. This checks the audit chain but cannot detect an entirely rewritten, unanchored history.
3. An independent append-only service must record the commitment digest and successive chain heads, with authenticated identity, trustworthy timestamps and access controls. Store its immutable receipts separately. This module does not create such a service or authenticate its responses.
4. Supply those externally retrieved receipts to `verifyHoldoutAnchorReceipts(commitment, entries, receipts)`. Every receipt binds the same commitment, an increasing event count and exact historical head. Missing/reordered receipts, rewritten heads, truncated histories, duplicate references and impossible timestamp order fail closed.
5. `NO_ANCHOR` means nothing is pinned; `PARTIALLY_ANCHORED_UNVERIFIED` means trailing events remain unpinned; `HEAD_MATCH_UNVERIFIED` means the supplied final head matches, **not** that any receipt is genuine. No status authorizes a trading order, deployment or a profitability claim.

Run: `cd frontend && node --experimental-strip-types --test tests/holdout-anchor-verification.test.ts`.

All test inputs are synthetic. Neither the anchor comparison nor the prior hash chain prevents a malicious actor from omitting an access event, using a different dataset, fabricating an external receipt or leaking holdout outcomes through another channel. Before declaring an untouched holdout, independent reviewers must verify the anchor service's actual records, access enforcement and source-data provenance. No real-money order or broker integration is introduced.
