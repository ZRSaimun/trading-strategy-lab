"""Offline, receipt-rounding-aware cost feasibility of frozen M1 CRT/ICT signals.

This is descriptive algebra on exploratory archive means, never an executable
spread estimate, an independently replicated result or trading authorization.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_CEILING, ROUND_FLOOR, localcontext
import hashlib

HALF_UNIT = Decimal("0.0000005")  # v1 round(..., 6) mean uncertainty
OUTPUT_UNIT = Decimal("0.0000001")


def _outward(value: Decimal, *, lower: bool) -> str:
    mode = ROUND_FLOOR if lower else ROUND_CEILING
    return format(value.quantize(OUTPUT_UNIT, rounding=mode), "f")


def _bounds(value: Decimal, radius: Decimal) -> dict[str, str]:
    return {
        "lower_bps": _outward(value - radius, lower=True),
        "upper_bps": _outward(value + radius, lower=False),
    }


def _verdict(low: Decimal, high: Decimal, cost: Decimal) -> str:
    if low > cost:
        return "POSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"
    if high <= cost:
        return "NONPOSITIVE_UNDER_RECEIPT_ROUNDING_ONLY"
    return "ROUNDING_BOUNDARY_UNKNOWN"


def _group_frontier(entries: list[tuple[str, int, Decimal | None]], costs: tuple[int, ...]):
    """Compute descriptive cost thresholds from already validated v1 receipts.

    Every rounded original archive mean is enclosed by +/- 0.5 micro-bps;
    the weighted fixed-sign mean has the same worst-case absolute radius.
    An archive-specific sign oracle is a hindsight-only impossibility bound.
    """
    entries = sorted(entries)
    count = sum(n for _, n, _ in entries)
    complete = all(n > 0 and gross is not None for _, n, gross in entries)
    if not complete:
        return {
            "status": "INCOMPLETE_ARCHIVE_COVERAGE",
            "evaluated_outcome_count": count,
            "break_even_roundtrip_cost_intervals_bps": None,
            "scenarios_by_illustrative_cost_bps": {str(c): None for c in costs},
        }
    with localcontext() as ctx:
        ctx.prec = 64
        fixed = sum((Decimal(n) * gross for _, n, gross in entries), Decimal(0)) / Decimal(count)
        oracle = sum((Decimal(n) * abs(gross) for _, n, gross in entries), Decimal(0)) / Decimal(count)
        # abs(x) can approach zero if the rounded x is within HALF_UNIT of zero.
        oracle_lower = sum((Decimal(n) * max(Decimal(0), abs(gross) - HALF_UNIT)
                            for _, n, gross in entries), Decimal(0)) / Decimal(count)
        oracle_upper = oracle + HALF_UNIT
        threshold = {
            "fixed_direction": _bounds(fixed, HALF_UNIT),
            "mirrored_direction": _bounds(-fixed, HALF_UNIT),
            "hindsight_per_archive_oracle": {
                "lower_bps": _outward(oracle_lower, lower=True),
                "upper_bps": _outward(oracle_upper, lower=False),
            },
        }
        scenarios = {}
        for c in costs:
            cost = Decimal(c)
            scenarios[str(c)] = {
                "fixed_direction": _verdict(fixed - HALF_UNIT, fixed + HALF_UNIT, cost),
                "mirrored_direction": _verdict(-fixed - HALF_UNIT, -fixed + HALF_UNIT, cost),
                "hindsight_per_archive_oracle": _verdict(oracle_lower, oracle_upper, cost),
            }
        return {
            "status": "INSUFFICIENT_ARCHIVE_REPLICATION" if len(entries) < 2 else "DESCRIPTIVE_COST_FEASIBILITY_ONLY",
            "evaluated_outcome_count": count,
            "break_even_roundtrip_cost_intervals_bps": threshold,
            "scenarios_by_illustrative_cost_bps": scenarios,
        }


def audit_m1_cost_frontier(reports):
    """Bound cost thresholds; reject self-reports that violate v1 precision.

    All original receipt, duplicate, source-isolation and count checks are
    delegated to the existing archive robustness and census auditors first.
    """
    from app.offline_m1_archive_robustness import audit_m1_archive_robustness
    from app.offline_m1_multi_archive_census import COSTS, POLICY, _canonical, _check

    baseline = audit_m1_archive_robustness(reports)
    groups = defaultdict(list)
    for report in reports:
        source, count, gross = _check(report)
        # The original v1 engine emitted round(value, 6) for all summaries.
        # Without this precision check, +/- HALF_UNIT is not a valid bound.
        for part in ("development_exploratory", "later_exploratory_not_holdout", "all_exploratory"):
            summary = report[part]
            values = [summary["mean_gross_bps"], summary["gross_win_fraction"]]
            values.extend(summary["mean_net_bps_by_roundtrip_cost"].values())
            for value in values:
                if value is not None:
                    d = Decimal(str(value))
                    if d != d.quantize(Decimal("0.000001")):
                        raise ValueError("Original v1 receipt precision exceeds six decimals")
        groups[(source["instrument"], source["provider"])].append(
            (source["archive_sha256"], count, gross)
        )
    output = []
    for (instrument, provider), entries in sorted(groups.items()):
        frontier = _group_frontier(entries, COSTS)
        output.append({
            "instrument": instrument,
            "provider": provider,
            "archive_count": len(entries),
            "archive_sha256": sorted(sha for sha, _, _ in entries),
            **frontier,
        })
    body = {
        "policy": POLICY,
        "source_robustness_sha256": baseline["research_sha256"],
        "cost_grid_bps": list(COSTS),
        "receipt_rounding_half_width_bps": "0.0000005",
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
            "These are algebraic cost thresholds from self-hashed, six-decimal "
            "exploratory archive means, not observed spreads or guaranteed profits. "
            "The per-archive direction oracle uses future data and is untradeable. "
            "Archive labels are not chronology; price side, UTC, licensing, "
            "financing, slippage, independent holdouts and fills are unverified."
        ),
    }
