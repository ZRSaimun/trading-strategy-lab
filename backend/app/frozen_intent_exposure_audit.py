"""Offline, read-only potential exposure-overlap audit for frozen M1 intents.

An intent's actual exit is unknowable at freeze time. Assume it could remain
open through the entire declared horizon. This deliberately overstates possible
simultaneous positions and never authorizes an order or reports a trading edge.
"""
from __future__ import annotations

import heapq
import re

from app.frozen_next_open_intent import fingerprint_next_open_intents

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_CLOCK = 8640000000


def audit_frozen_intent_exposure(manifest: dict, expected_manifest_sha256: str, *, sample_limit: int = 20) -> dict:
    """Check conservative full-horizon overlap without selecting away signals.

    Every eligible intent is included, even when overlapping. Endpoints are
    half-open, so an exit exactly when another entry starts is not overlapping.
    A caller-supplied hash is only a consistency check, not independent proof
    that the manifest existed before any market outcomes.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid sample limit")
    if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
        raise ValueError("Expected external SHA-256 required")
    digest = fingerprint_next_open_intents(manifest)  # Existing strict schema gate.
    if digest != expected_manifest_sha256:
        raise ValueError("Frozen intent fingerprint mismatch")

    horizon = manifest["source"]["horizon_minutes"] * 60
    ordered = sorted(manifest["eligible_intents"], key=lambda x: (x["signal_at"], x["path_id"]))
    active_ends = []
    overlap_pairs = 0
    peak = 0
    overlapping_ids = set()
    examples = []
    previous = None
    for row in ordered:
        start = row["signal_at"] + 60
        end = start + horizon
        if end > _MAX_CLOCK:
            raise ValueError("Declared exposure horizon exceeds supported clock")
        while active_ends and active_ends[0] <= start:
            heapq.heappop(active_ends)
        overlap_pairs += len(active_ends)
        if previous is not None and start < previous[1]:
            overlapping_ids.add(previous[0])
            overlapping_ids.add(row["path_id"])
            if len(examples) < sample_limit:
                examples.append(dict(first_path_id=previous[0], second_path_id=row["path_id"],
                                     second_entry_at=start))
        heapq.heappush(active_ends, end)
        peak = max(peak, len(active_ends))
        previous = (row["path_id"], end)

    excluded = len(manifest["excluded_signals"])
    status = ("POTENTIAL_EXPOSURE_COLLISIONS" if overlap_pairs else
              "DECLARED_PRE_SIGNAL_EXCLUSIONS" if excluded else
              "NO_FULL_HORIZON_OVERLAP_OBSERVED")
    return dict(
        protocol="frozen-next-open-exposure-overlap-v1", manifest_sha256=digest,
        status=status, eligible_intents=len(ordered), declared_excluded_signals=excluded,
        assumed_horizon_minutes=manifest["source"]["horizon_minutes"],
        potential_overlapping_pairs=overlap_pairs,
        eligible_intents_in_potential_overlaps=len(overlapping_ids),
        maximum_potential_concurrent_intents=peak,
        adjacent_overlap_samples=examples, sample_limit=sample_limit,
        overlap_free_under_full_horizon=overlap_pairs == 0,
        complete_against_supplied_manifest=True,
        independent_preregistration_verified=False, source_authenticated=False,
        source_rights_verified=False, observed_exit_times_verified=False,
        independent_trade_returns_established=False, verified_profitability=False,
        may_execute_order=False,
        warning=("Potential overlap assumes every intent remains open for its full horizon; "
                 "earlier exits could reduce actual concurrency. Do not drop overlapping signals "
                 "or treat them as independent trade returns. The supplied manifest may be incomplete "
                 "or retrospectively constructed; this is not an executable position ledger."),
    )
