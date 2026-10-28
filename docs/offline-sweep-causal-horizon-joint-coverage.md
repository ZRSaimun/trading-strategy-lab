# Causal confirmation vs retrospective horizon structural coverage

**Disconnected offline research diagnostic, not a strategy filter or trading signal.**

The function app.offline_sweep_causal_horizon_joint_coverage.audit_causal_horizon_joint_coverage builds a mutually exclusive **3 × 4** structural census for each frozen original-bar-index cohort (70/30 chronological split with 16-bar embargo). It accepts the same validated source-local M15 Bar population, sorted caller-declared duplicate M1 minutes, declared dataset ID and archive SHA-256 as the existing duplicate-bucket sensitivity auditor.

Causal rows use **only** 16 completed prior bars, the sweep and the completed confirmation: gap_or_segment, declared_duplicate_touched, quarantine_clean. Retrospective columns additionally inspect **16 future M15 bars** and classify outside_cohort_or_archive, gap_or_segment, declared_duplicate_touched, quarantine_clean. Each possible sweep index belongs to exactly one cell. The joint row totals must match the existing causal coverage report; column totals must match the existing full-horizon coverage report. A full-horizon clean window must always have a clean causal window.

This prevents a common denominator error: **full-horizon cleanliness is not knowable at signal confirmation**. For example, a declared duplicate bucket occurring only after confirmation can make a causally clean window retrospectively unclean. Excluding such a candidate *at signal time* would leak future information. The new report makes the distinction visible without changing the original research engine, no-overlap scheduling, prices, costs, embargo or cohort membership.

Example (offline Python):

    from app.offline_sweep_causal_horizon_joint_coverage import audit_causal_horizon_joint_coverage
    report = audit_causal_horizon_joint_coverage(
        bars, duplicate_m1_times,
        dataset_id=dataset_sha256, archive_sha256=original_zip_sha256)
    print(report["cohorts"]["development"]["causal_by_retrospective_horizon"])

The report is **not** a matched-trade effect estimate, signal census, verified entry/exit count, broker-fill estimate, or evidence of profit. The future horizon may be unobservable even when a trade would have exited early; this is a structural maximum-horizon envelope, not a censoring diagnosis for individual trades. Historical duplicate minutes are caller-declared until original archive custody and source row parity are independently verified. Source-local timestamps are not authenticated UTC; Loop 1 UTC bucket fingerprints cannot be compared without an independently verified offset, source session convention and anchor custody.

Synthetic regression tests cover duplicate buckets inside causal and future-only windows, overlapping duplicates, gaps, split/archive boundaries, price-only mutation invariance, invalid declarations and empty candidate populations. No private archives or broker data are needed for those tests. No production route, paid feed, database write, credentials, paper orders, live broker orders or deployment is enabled. Preserve the release gate for independent backup restoration, rollback, health and hosting checks.
