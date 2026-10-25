# Offline archive inventory drift (Loop 1)

Compare **two independently generated, untrusted scanner audit JSON files** from separate collection or validation runs, without opening source ZIPs or modifying a dataset:

```sh
cd backend
PYTHONPATH=. python -m app.archive_inventory_drift --previous /private/audit-old.json --current /private/audit-new.json
PYTHONPATH=. python -m pytest -q tests/test_archive_inventory_drift.py
```

Both inputs must pass the existing strict `histdata_audit_triage` arithmetic, source-label and fail-closed rights checks. The CLI refuses symlinks, non-regular files, duplicate JSON keys, unbounded files, and invalid claims. It reports filename additions/removals, changes to the **reported ZIP SHA-256** for a stable filename, changes in source/clock/coverage/canonical-digest claims, and possible renamed-file aliases with the same reported byte digest. Examples are bounded and never include raw hashes or prices. All comparisons are **scanner claims**, not verification of the original bytes or provider.

A changed ZIP digest is not necessarily a price revision; a changed scanner metadata field with the same ZIP digest can reflect parser/configuration changes. Neither observation establishes malicious alteration. A possible renamed file is not a second independent source. This tool does not fix duplicate minutes, infer DST, check a market calendar, verify provider entitlements or usage rights, or authorize backtesting. `research_ready`, `can_auto_import`, `live`, and `may_execute_order` remain false.

Do not merge/deploy this draft until latest-head CI, reconciliation against `main`, independently verified ZIP provenance and licensing, disposable staging acceptance, production backup restore/rollback and health checks are complete. Coordinate original ZIP format parity with PR #43 and research readiness with PR #41.
