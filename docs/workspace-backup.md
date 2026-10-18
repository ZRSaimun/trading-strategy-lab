# Browser workspace backup and recovery — v0.9

## Save

In the GitHub Pages browser-local app, open **Backup & Restore → Download workspace backup**. Use the browser's download/save-file controls to keep the JSON file outside browser storage, for example in your private Files folder. The application cannot verify that your phone completed saving a downloaded file.

The snapshot includes the two exact imported instrument datasets and source metadata, manual drawings and versions, watchlist, saved backtests, journal, replay alert rules, retained events and up to 200 audit records. It does not include credentials, theme settings, external display settings or unsaved UI edits. Saved report equity traces remain sampled as in the original records. This is a snapshot of retained records, not recovery of history already pruned by application limits.

Backups are unencrypted. They contain private research; store them securely. There is no upload, cloud synchronization or account authentication in browser-local mode. This does not change the public deployment's access model.

## Restore

1. Download a current backup before replacing anything.
2. Close other tabs using this app, and finish any edits.
3. Choose your own trusted workspace JSON backup.
4. Tick the explicit replacement checkbox and select **Validate & replace workspace**.
5. After successful replacement the page reloads. Reopen the datasets, drawings and research views to inspect restored records.

Restore replaces, rather than merges, the entire browser database's records. Snapshot metadata, SHA-256 checksum, format version, allowed storage keys, instrument identities, dataset prices/timestamps/coverage, drawing coordinates, research record structure, record counts and file size are validated first. The checksum covers the serialized entries and detects accidental modifications, not identity or authenticity. Research payload validation is structural; it does not certify results, rerun a backtest or verify data licensing. Do not restore untrusted third-party files.

A single IndexedDB read transaction produces each snapshot. Pending same-tab writes are ordered before export/restore; queued replay-alert processing is awaited before restore. Atomic replacement uses one read-write transaction. Synchronous errors or transaction aborts roll back the replacement. A restored audit trail gets a new `workspace.restore` record. Browser quota and available device memory may still prevent recovery, with an error shown.

Limits: 64 MB file; the same underlying dataset and research retention caps as the running app. No cross-tab coordination, encryption, scheduled backups, server restore, cross-version migration or physical iPhone/Safari verification. Only version 1 backup format is supported. Restore does not activate a feed or make historical data live.

## Acceptance evidence

Fake IndexedDB integration tests exercise a full roundtrip with deterministic software-only candles, source metadata, drawings, generated reports, journal, watchlist, rules and generated alert events; rejection of damaged checksums, malformed JSON, unsupported versions, duplicate keys, wrong instruments and invalid coordinates; explicit replacement confirmation; ordered export; replacement rather than merge; and synchronous and asynchronous rollback failures followed by successful recovery. No market dataset is bundled or fabricated for use as real data. Browser download/file-picker flow remains unverified in this environment.

For private Docker deployments use the separate database backup/restore instructions in security.md; browser backups are not exposed by the server API.
