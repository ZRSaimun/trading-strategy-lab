"""Read-only population continuity audit from completed M1 bars to frozen intents.

Recomputes the fixed detector and ATR compiler; no outcomes, quote fills, trades,
external data access or storage. Caller hashes are consistency anchors only.
"""
import re

from app.causal_atr_intent_bridge import compile_causal_atr_intents
from app.causal_m1_confluence_detector import detect_completed_m1_confluence

_SHA = re.compile(r"[0-9a-f]{64}\Z")


def _require_digest(value, label):
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256 digest")


def audit_causal_m1_lineage(
    source, bars, observed_through_close_at, expected_snapshot_sha256,
    expected_manifest_sha256=None, expected_pre_signal_evidence_sha256=None,
    *, sample_limit=20,
):
    """Reconstruct the entire declared M1 scan, not a handpicked candidate subset.

    The snapshot SHA must have been captured independently before this review.
    For a nonempty candidate population both ATR hashes are mandatory. A
    zero-candidate scan cannot be disguised as a successful backtest.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid sample limit")
    _require_digest(expected_snapshot_sha256, "Expected snapshot")
    scan = detect_completed_m1_confluence(source, bars, observed_through_close_at)
    if scan["snapshot_sha256"] != expected_snapshot_sha256:
        raise ValueError("Completed-M1 snapshot fingerprint mismatch")

    candidates = scan["candidates"]
    if not candidates:
        if expected_manifest_sha256 is not None or expected_pre_signal_evidence_sha256 is not None:
            raise ValueError("No candidates: ATR hashes must be absent, not fabricated")
        return dict(
            protocol="causal-m1-detector-to-intent-lineage-v1",
            status="NO_CANDIDATES_NOT_A_BACKTEST",
            snapshot_sha256=scan["snapshot_sha256"],
            manifest_sha256=None, pre_signal_evidence_sha256=None,
            confirmed_candidates=0, eligible_intents=0, declared_exclusions=0,
            sweep_count=scan["sweep_count"], expired_sweeps=scan["expired_sweeps"],
            pending_sweeps=scan["pending_sweeps"],
            gap_censored_sweeps=scan["gap_censored_sweeps"],
            ambiguous_double_sweeps=scan["ambiguous_double_sweeps"],
            sample_limit=sample_limit, candidate_samples=[],
            complete_against_supplied_snapshot=True,
            pre_signal_population_reconciled=True,
            independent_preregistration_verified=False, source_authenticated=False,
            source_rights_verified=False, untouched_holdout_verified=False,
            executable_quotes_verified=False, verified_profitability=False,
            may_execute_order=False,
            warning="No confirmed candidates; not a backtest. A self-declared snapshot digest is not independent registration, licensed provenance, or a profit claim.",
        )

    _require_digest(expected_manifest_sha256, "Expected manifest")
    _require_digest(expected_pre_signal_evidence_sha256, "Expected pre-signal evidence")
    frozen = compile_causal_atr_intents(source, candidates)
    # Reconcile *every* detector candidate against exactly one eligible or
    # explicitly excluded frozen signal; never silently remove failures.
    population = {
        (c["path_id"], c["confirmation_close_at"] - 60): c
        for c in candidates
    }
    manifest = frozen["manifest"]
    emitted = manifest["eligible_intents"] + manifest["excluded_signals"]
    emitted_keys = {(row["path_id"], row["signal_at"]) for row in emitted}
    if (len(population) != len(candidates) or len(emitted_keys) != len(emitted)
            or set(population) != emitted_keys
            or len(emitted) != frozen["candidate_count"]):
        raise ValueError("Detector-to-frozen-intent population mismatch")
    for row in manifest["eligible_intents"]:
        if row["direction"] != population[(row["path_id"], row["signal_at"])]["direction"]:
            raise ValueError("Detector-to-frozen-intent direction mismatch")
    if frozen["manifest_sha256"] != expected_manifest_sha256:
        raise ValueError("Frozen intent manifest fingerprint mismatch")
    if frozen["pre_signal_evidence_sha256"] != expected_pre_signal_evidence_sha256:
        raise ValueError("Pre-signal evidence fingerprint mismatch")

    excluded_keys = {(r["path_id"], r["signal_at"]) for r in manifest["excluded_signals"]}
    examples = [
        dict(path_id=c["path_id"], confirmation_close_at=c["confirmation_close_at"],
             direction=c["direction"],
             status=("DECLARED_EXCLUSION" if (c["path_id"], c["confirmation_close_at"] - 60)
                     in excluded_keys else "FROZEN_ELIGIBLE"))
        for c in sorted(candidates, key=lambda c: (c["confirmation_close_at"], c["path_id"]))[:sample_limit]
    ]
    return dict(
        protocol="causal-m1-detector-to-intent-lineage-v1",
        status=("PRE_SIGNAL_EXCLUSIONS_NO_POPULATION_RETURN" if frozen["excluded_count"]
                else "COMPLETE_RECONSTRUCTION_NOT_VALIDATED_EDGE"),
        snapshot_sha256=scan["snapshot_sha256"],
        manifest_sha256=frozen["manifest_sha256"],
        pre_signal_evidence_sha256=frozen["pre_signal_evidence_sha256"],
        confirmed_candidates=len(candidates), eligible_intents=frozen["eligible_count"],
        declared_exclusions=frozen["excluded_count"],
        sweep_count=scan["sweep_count"], expired_sweeps=scan["expired_sweeps"],
        pending_sweeps=scan["pending_sweeps"],
        gap_censored_sweeps=scan["gap_censored_sweeps"],
        ambiguous_double_sweeps=scan["ambiguous_double_sweeps"],
        sample_limit=sample_limit, candidate_samples=examples,
        complete_against_supplied_snapshot=True,
        pre_signal_population_reconciled=True,
        independent_preregistration_verified=False, source_authenticated=False,
        source_rights_verified=False, untouched_holdout_verified=False,
        executable_quotes_verified=False, verified_profitability=False,
        may_execute_order=False,
        warning=("Recomputed full supplied M1 snapshot and reconciled every confirmation to "
                 "the frozen ATR manifest. Hashes are consistency checks only; they do not "
                 "establish independent preregistration, source rights, untouched holdouts, "
                 "bid/ask fills, execution costs, or profitable returns. Never discard exclusions."),
    )
