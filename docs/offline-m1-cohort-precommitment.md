# Outcome-free archive-cohort precommitment (exploratory M1)

## Why

The existing original-v1 M1 receipt census rejects duplicate archives and withholds performance when an **included** archive has no outcomes. It cannot know whether a researcher **omitted** an inconvenient archive before invoking the census. This new disconnected offline fence compares evaluated receipts against an independently retained *pre-outcome* cohort identity digest.

## Two-stage protocol

1. **Before looking at outcomes**, inventory the intended source-local original archives and candle-manifest identities. Each entry must contain exactly `instrument`, `provider`, `archive_sha256` and `bar_manifest_sha256`. Both hashes are lowercase 64-character SHA-256; no raw prices or trades are included. Distinct archive and manifest hashes are required globally. The frozen policy and exact canonical sorted identity list are SHA-256 committed.
2. Call `app.offline_m1_cohort_precommitment.prepare_m1_cohort_precommitment(entries)`. **Independently retain the returned `source_cohort_sha256` before any outcome evaluation** (e.g., a separately witnessed dated record). A digest generated after outcomes is not a valid precommitment.
3. After producing the original-v1 self-hashed reports, call `require_m1_precommitted_cohort(reports, independently_retained_digest)`. It first validates the full existing census, including per-archive hashes, frozen cost scenarios, count reconciliation and incomplete-archive quarantine. It then rejects any omitted, added, substituted, renamed, or re-manifested archive, even when the remaining receipts alone would be a valid census. Order does not affect the commitment.
4. If any archive has no evaluated outcomes, the existing cohort-level `INCOMPLETE_ARCHIVE_COVERAGE` quarantine remains in force; the gate never imputes a zero return or silently drops it.

Example (schematic, **not** real archive identifiers):

~~~python
from app.offline_m1_cohort_precommitment import (
    prepare_m1_cohort_precommitment, require_m1_precommitted_cohort,
)
# BEFORE outcomes: identities must come from an independently controlled inventory.
precommit = prepare_m1_cohort_precommitment(pre_outcome_entries)
# Retain precommit["source_cohort_sha256"] independently and immutably.
# LATER: use the independently retained digest, not a freshly computed one.
result = require_m1_precommitted_cohort(original_v1_reports, registered_digest)
~~~

## Scope and limitations

- This is **not** cryptographic proof of registration time, archive authenticity, rights, source UTC convention, vendor price side, chronological holdout status, statistical significance or an executable trading edge. A dishonest researcher could select archives before registration, or recompute the expected digest after results. An external trusted registration process is indispensable.
- The digest commits to identity, not contents of each trade outcome. Original v1 receipts remain self-hashed declarations and must be independently replayed against authenticated source data.
- The current 32-archive exploratory results were **not** rerun here, nor have independently pre-outcome-registered manifests been produced for those exposed archives. No claim that those results are protected or preregistered is warranted.
- This offline code makes no network or broker calls, performs no writes, does not enable alerts or orders, and has `trade_authorized=False` in its outputs. No historical archives, raw prices, secrets or licensed data are included.
- Costs 0/5/10/20 bps remain illustrative, not verified BID/ASK, slippage, financing or commission. Do not merge or deploy before full exact-head CI and independent restore/rollback/authenticated-health gates.

Run synthetic regression:

~~~sh
cd backend
PYTHONPATH=. python -m pytest -q tests/test_offline_m1_cohort_precommitment.py
~~~
