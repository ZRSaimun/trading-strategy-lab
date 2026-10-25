# Offline signed holdout anchors (Loop 3)

`frontend/lib/holdout-signed-anchor.ts` verifies pinned-key **Ed25519** signatures on supplied holdout audit-head receipts. It first rechecks the **full** source-identified commitment and audit hash chain, rejects recorded contamination, and compares every anchored head. The signature payload has a domain prefix, fixed field order and key ID. It rejects untrusted keys, authority substitution, modified receipts, malformed signatures, and duplicate signing identities.

## Trust boundary

1. Independently verify authorized raw archive SHA-256, source identity, license, UTC conventions and label clocks; preregister the protocol before inspecting holdout outcomes.
2. Have an **independent** append-only service sign `holdoutAnchorSigningMessage(keyId, receipt)` with Ed25519, retaining the receipt outside the research workspace. That service must authenticate users, enforce append-only storage and independently attest time. **This module does not implement or contact the service.**
3. Authenticate its **raw 32-byte public key** out of band, and pin `{keyId,authority,publicKeyBase64url}`. Never trust a key distributed together with an untrusted receipt.
4. Run `verifySignedHoldoutAnchors(commitment, entries, signedAnchors, trustedKeys)`. `HEAD_SIGNED_TIME_UNVERIFIED` means the supplied final head is signed by a pinned key; `PARTIALLY_SIGNED_TIME_UNVERIFIED` means trailing events remain unanchored; `NO_SIGNED_ANCHOR` means no receipt. **None certifies timestamps or an untouched holdout.**
5. Independently audit the actual service's retention, timestamps, keys and complete access logs, then compare original archive digests and provenance.

Run `cd frontend && node --experimental-strip-types --test tests/holdout-signed-anchor.test.ts` (Node 22).

**Limits:** A signature authenticates a key's assertion only when the key was independently pinned. The signer could backdate or omit events; other channels could leak outcomes; archive identities could be fabricated. No real multi-year returns, executable CFD spreads, slippage, financing, actual demo fills or trading edge are established. This is disconnected research code: no network, credentials, orders, paid services or production integration. Do not deploy without backup, rollback and health verification.
