"""Bounded whole-archive deletion stress on unauthenticated exploratory receipts.

Descriptive stress only. Not a bootstrap, confidence interval, or trade gate.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_HALF_EVEN, localcontext
from itertools import combinations
import hashlib

from app.offline_m1_archive_robustness import audit_m1_archive_robustness
from app.offline_m1_multi_archive_census import COSTS, POLICY, _canonical, _check

MAX_REMOVED_ARCHIVES = 3
SCALE = Decimal("0.000001")


def _six(value):
    return float(value.quantize(SCALE, rounding=ROUND_HALF_EVEN)) if value is not None else None


def audit_m1_archive_deletion_stress(reports):
    """Report exact extrema after removing 1..3 complete archives per source.

    A missing/empty archive makes every deletion statistic in that source
    unknown. No ordering of archive SHA identities is interpreted as time.
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
            entries.sort(key=lambda item: item[0])
            complete = all(n > 0 and gross is not None for _, n, gross in entries)
            total = sum(n for _, n, _ in entries)
            gross_sum = sum((n * gross for _, n, gross in entries if gross is not None), Decimal(0))
            stresses = {}
            for k in range(1, MAX_REMOVED_ARCHIVES + 1):
                if not complete or len(entries) <= k:
                    stresses[str(k)] = {
                        "evaluated_combinations": 0,
                        "minimum_remaining_outcomes": None,
                        "maximum_remaining_outcomes": None,
                        "scenarios_by_illustrative_cost_bps": {
                            str(cost): {"min_net_bps": None, "max_net_bps": None}
                            for cost in COSTS
                        },
                    }
                    continue
                low, high = None, None
                min_remaining, max_remaining, evaluated = None, None, 0
                for removed in combinations(entries, k):
                    removed_count = sum(n for _, n, _ in removed)
                    remaining = total - removed_count
                    if remaining <= 0:
                        raise ValueError("No remaining evaluated outcomes")
                    removed_gross = sum((n * gross for _, n, gross in removed), Decimal(0))
                    mean = (gross_sum - removed_gross) / remaining
                    low = mean if low is None else min(low, mean)
                    high = mean if high is None else max(high, mean)
                    min_remaining = remaining if min_remaining is None else min(min_remaining, remaining)
                    max_remaining = remaining if max_remaining is None else max(max_remaining, remaining)
                    evaluated += 1
                stresses[str(k)] = {
                    "evaluated_combinations": evaluated,
                    "minimum_remaining_outcomes": min_remaining,
                    "maximum_remaining_outcomes": max_remaining,
                    "scenarios_by_illustrative_cost_bps": {
                        str(cost): {"min_net_bps": _six(low - cost), "max_net_bps": _six(high - cost)}
                        for cost in COSTS
                    },
                }
            output.append({
                "instrument": instrument,
                "provider": provider,
                "archive_count": len(entries),
                "evaluated_outcome_count": total,
                "status": ("INCOMPLETE_ARCHIVE_COVERAGE" if not complete else
                           "INSUFFICIENT_ARCHIVE_REPLICATION" if len(entries) < 2 else
                           "DESCRIPTIVE_DELETION_STRESS_ONLY"),
                "deletion_by_whole_archive_count": stresses,
            })
    body = {
        "policy": POLICY,
        "source_robustness_sha256": baseline["research_sha256"],
        "cost_grid_bps": list(COSTS),
        "max_removed_archives": MAX_REMOVED_ARCHIVES,
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
        "warning": "Exact whole-archive deletion extrema are descriptive only; archive selection is not random, receipt hashes do not authenticate vendors, timestamps and overlap are unverified, and illustrative bps costs are not executable fills or financing. No confidence interval, protected holdout, profitability, or trade permission.",
    }
