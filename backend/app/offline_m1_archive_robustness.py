"""Offline archive-level fragility stress for frozen, unauthenticated M1 receipts.

This is a descriptive sensitivity audit, not a confidence interval or trade gate.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib
import json

from app.offline_m1_multi_archive_census import (
    COSTS, POLICY, _check, _canonical, audit_m1_multi_archive_census,
)

MAX_ARCHIVE_OUTCOMES = 500_000
MAX_ABS_MEAN_BPS = Decimal("1000000")
SCALE = Decimal("0.000001")


def _six(value):
    if value is None:
        return None
    return float(value.quantize(SCALE, rounding=ROUND_HALF_EVEN))


def audit_m1_archive_robustness(reports):
    """Compare archive-balanced and trade-balanced means and deletion stress.

    Accepts only original v1 reports already validated by the source-isolated
    census. No archive ordering, independent observations, or execution claims.
    """
    census = audit_m1_multi_archive_census(reports)
    groups = defaultdict(list)
    for report in reports:
        source, count, gross = _check(report)
        if count > MAX_ARCHIVE_OUTCOMES or count > report["bar_count"]:
            raise ValueError("Archive outcome count exceeds original bar limit")
        if gross is not None and abs(gross) > MAX_ABS_MEAN_BPS:
            raise ValueError("Implausibly large unverified archive mean")
        groups[(source["instrument"], source["provider"])].append(
            (source["archive_sha256"], count, gross)
        )
    output = []
    with localcontext() as ctx:
        ctx.prec = 64
        for (instrument, provider), entries in sorted(groups.items()):
            entries.sort(key=lambda e: e[0])
            nonempty = [(sha, n, gross) for sha, n, gross in entries if n]
            total = sum(n for _, n, _ in nonempty)
            k = len(nonempty)
            weighted_gross = sum((n * gross for _, n, gross in nonempty), Decimal(0)) / total if total else None
            balanced_gross = sum((gross for _, _, gross in nonempty), Decimal(0)) / k if k else None
            worst_gross = min((gross for _, _, gross in nonempty), default=None)
            best_gross = max((gross for _, _, gross in nonempty), default=None)
            deletion_gross = []
            if k >= 2:
                for _, n, gross in nonempty:
                    # An archive is the deletion unit; do not pretend trades are IID.
                    deletion_gross.append((weighted_gross * total - n * gross) / (total - n))
            scenarios = {}
            for cost in COSTS:
                dcost = Decimal(cost)
                scenarios[str(cost)] = {
                    "trade_weighted_net_bps": _six(weighted_gross - dcost) if total else None,
                    "equal_archive_net_bps": _six(balanced_gross - dcost) if k else None,
                    "worst_archive_net_bps": _six(worst_gross - dcost) if k else None,
                    "best_archive_net_bps": _six(best_gross - dcost) if k else None,
                    "leave_one_archive_out_min_net_bps": _six(min(deletion_gross) - dcost) if deletion_gross else None,
                    "leave_one_archive_out_max_net_bps": _six(max(deletion_gross) - dcost) if deletion_gross else None,
                    "archive_means_positive_after_cost": sum(gross > dcost for _, _, gross in nonempty),
                }
            status = ("NO_EVALUATED_ARCHIVES" if k == 0 else
                      "INCOMPLETE_ARCHIVE_COVERAGE" if k != len(entries) else
                      "INSUFFICIENT_ARCHIVE_REPLICATION" if k < 2 else
                      "DESCRIPTIVE_ARCHIVE_STRESS_ONLY")
            output.append({
                "instrument": instrument, "provider": provider,
                "archive_count": len(entries), "evaluated_archive_count": k,
                "empty_archive_count": len(entries) - k,
                "evaluated_outcome_count": total, "status": status,
                "scenarios_by_illustrative_cost_bps": scenarios,
                "archive_sha256": [sha for sha, _, _ in entries],
            })
    body = {
        "policy": POLICY,
        "source_census_sha256": census["research_sha256"],
        "cost_grid_bps": list(COSTS),
        "groups": output,
    }
    return {
        **body,
        "research_sha256": hashlib.sha256(_canonical(body).encode()).hexdigest(),
        "research_only": True,
        "trade_authorized": False,
        "verified_profitability": False,
        "protected_holdout": False,
        "executable_quotes_verified": False,
        "source_authenticity_verified": False,
        "statistical_significance_verified": False,
        "warning": "Descriptive archive-level deletion stress only; archive labels are not chronology, receipts are self-hashed and rounded, archive independence is not assumed, and no uncertainty interval, authenticated data, executable costs, untouched holdout or trade permission is established.",
    }
