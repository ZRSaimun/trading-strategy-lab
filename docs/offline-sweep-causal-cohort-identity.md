# Source-local causal sweep cohort identity fingerprints

**Offline structural research only.** `app.offline_sweep_causal_cohort_identity.audit_causal_cohort_identity` produces deterministic, domain-separated SHA-256 fingerprints of the **exact 18-bar causal candidate-window identities** (16 completed prior M15 bars, the sweep bar and completed confirmation). It accepts the same validated `Bar` list, sorted caller-declared duplicate M1 minutes, dataset ID and original archive SHA declaration as `audit_declared_duplicate_minutes`.

The result partitions every candidate sweep index under the frozen original-bar-index 70/30 split and 16-bar embargo into exactly one of: `gap_or_segment`, `declared_duplicate_touched`, or `quarantine_clean`. For each development and exploratory-later cohort, counts must reconcile to the existing causal coverage census. Each digest includes a versioned domain, declared dataset/archive identifiers, original M15 count, split index, cohort and class, followed by each candidate's original bar index and source-local sweep/confirmation timestamps. This makes cohort drift detectable when source-local timestamps, declared duplicate buckets or gap/segment eligibility change. It is not a trade or signal digest and does not include OHLC, positions, costs or outcomes.

Example from an offline Python session:

```python
from app.offline_sweep_causal_cohort_identity import audit_causal_cohort_identity

report = audit_causal_cohort_identity(
    bars, duplicate_m1_times,
    dataset_id=dataset_sha256,
    archive_sha256=original_zip_sha256,
)
```

`bars` must be the **same ordered complete source-local M15 population** supplied to the existing sensitivity auditor. Inputs are validated by that auditor, which also runs the frozen research comparison; this wrapper is therefore not a substitute for the original importer, a faster archive parser or a production API. Digests are computed only after validation. Tests use synthetic bars; this feature has not independently replayed original licensed archives.

## What a matching digest means

Within the **same declared source-local clock convention, input identity, original bar count and frozen split**, matching per-class hashes and counts provide reproducible evidence that the structural candidate-window identities agree. A hash mismatch is a stop-and-investigate condition, **not** proof of a price error, timezone error or market edge. These are unsalted integrity hashes, **not secrecy protection**; do not publish private manifests, prices or original ZIP contents.

Do **not** compare these source-local digests directly with Loop 1's UTC M15 bucket identity hashes. First independently establish the provider's source-local clock, DST/session convention, authenticated original ZIP/SQLite row parity and exact source-local-to-UTC bucket mapping. Even identical source-local fingerprints cannot prove correct price content, source rights, completed candle finality, broker-executable BID/ASK, financing, untouched holdout integrity or positive expectancy.

The candidate-window census uses **only completed-confirmation information**, never the future entry or 16-bar outcome horizon. It does not change the strategy, optimize parameters, select signals, submit paper/live orders, access paid feeds, touch production data or authorize broker actions. Production release remains gated by green CI and independent backup restoration, rollback, health and hosting verification.
