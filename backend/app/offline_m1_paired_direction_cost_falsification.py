"""Offline paired-direction cost falsification on original exploratory M1 receipts.

A hindsight direction choice is a diagnostic upper bound, NEVER a strategy.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
import hashlib

from app.offline_m1_archive_robustness import audit_m1_archive_robustness
from app.offline_m1_multi_archive_census import COSTS, POLICY, _canonical, _check

SCALE = Decimal("0.000001")


def _six(value):
    return float(value.quantize(SCALE, rounding=ROUND_HALF_EVEN)) if value is not None else None


def audit_m1_paired_direction_cost_falsification(reports):
    """Test fixed, exactly mirrored and impossible hindsight archive directions.

    The same frozen signal timestamps, entry prices, exit prices and overlap
    selection are assumed for the mirror; only each position sign changes.
    The archive oracle uses the *entire* archive's mean to pick its direction:
    this is future information and is deliberately never actionable.
    """
    baseline = audit_m1_archive_robustness(reports)
    groups = defaultdict(list)
    for report in reports:
        source, count, gross = _check(report)
        groups[(source["instrument"], source["provider"])].append(
            (source["archive_sha256"], count, gross)
        )
    output = []
    with localcontext() as ctx:
        ctx.prec = 64
        for (instrument, provider), entries in sorted(groups.items()):
            entries.sort(key=lambda entry: entry[0])
            complete = all(count > 0 and gross is not None for _, count, gross in entries)
            scenarios = {}
            if complete:
                total = sum(count for _, count, _ in entries)
                fixed = sum((count * gross for _, count, gross in entries), Decimal(0)) / total
                mirrored = -fixed
                hindsight = sum((count * abs(gross) for _, count, gross in entries), Decimal(0)) / total
            else:
                total = sum(count for _, count, _ in entries)
                fixed = mirrored = hindsight = None
            for cost in COSTS:
                c = Decimal(cost)
                scenarios[str(cost)] = {
                    "fixed_direction_net_bps": _six(fixed - c) if complete else None,
                    "mirrored_direction_net_bps": _six(mirrored - c) if complete else None,
                    "hindsight_per_archive_oracle_net_bps": _six(hindsight - c) if complete else None,
                    "fixed_positive_archive_count": (
                        sum(gross > c for _, _, gross in entries) if complete else None
                    ),
                    "mirrored_positive_archive_count": (
                        sum(-gross > c for _, _, gross in entries) if complete else None
                    ),
                    "hindsight_positive_archive_count": (
                        sum(abs(gross) > c for _, _, gross in entries) if complete else None
                    ),
                    "neither_direction_positive_for_any_archive_mean": (
                        all(abs(gross) <= c for _, _, gross in entries) if complete else None
                    ),
                }
            output.append({
                "instrument": instrument,
                "provider": provider,
                "archive_count": len(entries),
                "evaluated_outcome_count": total,
                "status": (
                    "INCOMPLETE_ARCHIVE_COVERAGE" if not complete else
                    "INSUFFICIENT_ARCHIVE_REPLICATION" if len(entries) < 2 else
                    "DESCRIPTIVE_HINDSIGHT_FALSIFICATION_ONLY"
                ),
                "scenarios_by_illustrative_cost_bps": scenarios,
                "archive_sha256": [sha for sha, _, _ in entries],
            })
    body = {
        "policy": POLICY,
        "source_robustness_sha256": baseline["research_sha256"],
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
        "source_authenticity_verified": False,
        "executable_quotes_verified": False,
        "statistical_significance_verified": False,
        "hindsight_oracle_is_tradable": False,
        "warning": (
            "The per-archive direction oracle uses future outcomes and cannot "
            "be traded. Archive-level mean sign inversion is not a new signal "
            "or a bound on all possible strategies. Original self-hashed "
            "receipts are not authenticated vendor data. Source-wall clocks, "
            "BID/ASK spreads, slippage, financing, untouched holdouts and "
            "broker execution remain unverified. No trading authorization."
        ),
    }
