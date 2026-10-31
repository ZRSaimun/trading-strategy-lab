# Declared broker snapshot anchor audit (offline, no execution)

`app.paper_broker_snapshot_anchor_audit` compares a bounded, fully validated broker snapshot chain against caller-supplied, previously recorded SHA-256 fingerprints. The module has no network, file, credential, broker or order-placement access.

`fingerprint_declared_snapshot` deterministically hashes the exact JSON snapshot fields with a versioned domain separator and byte length. `fingerprint_declared_chain` binds 2–16 ordered snapshot digests. Store the expected snapshot and chain fingerprints **before** later evidence can change, in independently controlled, immutable custody. An anchor supplied or recomputed by the same untrusted party as the snapshot is not evidence of authenticity or completeness.

`inspect_declared_snapshot_anchors(expected, snapshots, check_times_ms, prior_snapshot_digests, prior_chain_digest, max_checkpoint_gap_ms=60000)` first invokes the existing census, pairwise replay and chain audit. It then rejects changed snapshot content or a changed chain fingerprint with `HOLD_RECONCILIATION`. Invalid digest types, all-zero digests, incorrect lengths and population mismatches raise `ValueError` (fail closed). The caller is responsible for maintaining trusted checkpoint clocks, durable external custody, provider authentication and complete broker pagination.

A clean result is only `DECLARED_ANCHOR_CANDIDATE_UNVERIFIED`: it **never** authenticates broker records, clears UNKNOWN submissions, or enables paper/live orders. SHA-256 does not replace a digital signature or trusted audit store. No real broker integration is implied.
