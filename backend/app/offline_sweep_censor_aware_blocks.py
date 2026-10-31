"""Disconnected censor-aware moving-block sensitivity for declared entered trades.

Blocks sample the original entered-position sequence, including unknown exits.
Descriptive observed-only summaries are not unconditional expectancy or CIs.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from random import Random

COHORTS = ("development", "exploratory_later")
COST_BPS = (0, 5, 10, 20)


@dataclass(frozen=True)
class EnteredTrade:
    time: datetime  # Unauthenticated source-local clock, not UTC
    cohort: str
    gross_r: D | None  # None means unknown/censored exit
    entry: D
    risk: D


def _nearest_rank(values, numerator):
    if not values:
        return None
    return str(sorted(values)[max(0, (len(values) * numerator + 999) // 1000 - 1)])


def audit_censor_aware_blocks(trades, *, block_length=8, resamples=500,
                              seed=20261028):
    """Report cost/censor sensitivity without fabricating missing exit returns.

    The report is caller-declared, read-only and must not select a strategy.
    """
    if type(trades) not in (tuple, list) or len(trades) > 10000:
        raise ValueError("Expected at most 10000 declared entered positions")
    if (type(block_length) is not int or not 1 <= block_length <= 10000 or
            type(resamples) is not int or not 1 <= resamples <= 1000 or
            type(seed) is not int or not 0 <= seed < 2**63):
        raise ValueError("Invalid bounded resampling controls")
    by_cohort = {name: [] for name in COHORTS}
    last = None
    for trade in trades:
        if (not isinstance(trade, EnteredTrade) or
                type(trade.time) is not datetime or trade.time.tzinfo is not None or
                trade.cohort not in COHORTS or
                type(trade.entry) is not D or type(trade.risk) is not D or
                not trade.entry.is_finite() or not trade.risk.is_finite() or
                trade.entry <= 0 or trade.risk <= 0 or
                abs(trade.entry.adjusted()) > 18 or
                abs(trade.risk.adjusted()) > 18 or
                (trade.gross_r is not None and
                 (type(trade.gross_r) is not D or
                  not trade.gross_r.is_finite() or
                  abs(trade.gross_r.adjusted()) > 18))):
            raise ValueError("Invalid observed/censored trade geometry")
        if last is not None and trade.time <= last:
            raise ValueError("Entered positions must be strictly chronological")
        last = trade.time
        by_cohort[trade.cohort].append(trade)

    cohorts = {}
    for name, declared in by_cohort.items():
        n = len(declared)
        if n * resamples > 2000000:
            raise ValueError("Entered-position resampling work budget exceeded")
        observed = [t for t in declared if t.gross_r is not None]
        observed_count = len(observed)
        censor_count = n - observed_count
        gross = [t.gross_r for t in declared]
        unit_cost = [t.entry / (D(10000) * t.risk)
                     if t.gross_r is not None else None for t in declared]
        rng = Random(f"LOOP2_CENSOR_AWARE_ENTERED_BLOCKS_V1|{seed}|{name}")
        draws = []
        if n >= block_length:
            for _ in range(resamples):
                indices = []
                while len(indices) < n:
                    start = rng.randrange(n - block_length + 1)
                    indices.extend(range(start, start + block_length))
                indices = indices[:n]
                used = [i for i in indices if gross[i] is not None]
                k = len(used)
                draws.append((k, sum((gross[i] for i in used), D(0)),
                              sum((unit_cost[i] for i in used), D(0))))
        scenarios = []
        for bps in COST_BPS:
            original = (sum((t.gross_r - bps * t.entry /
                             (D(10000) * t.risk) for t in observed), D(0)) /
                        observed_count if observed_count else None)
            sample_means = [(g - bps * c) / k for k, g, c in draws if k]
            scenarios.append({
                "additional_round_trip_bps": bps,
                "observed_mean_net_r": str(original) if original is not None else None,
                "descriptive_p025_observed_mean_net_r": _nearest_rank(sample_means, 25),
                "descriptive_p975_observed_mean_net_r": _nearest_rank(sample_means, 975),
                "draws_with_observed_exits": len(sample_means),
                "draws_with_no_observed_exits": len(draws) - len(sample_means),
            })
        censor_fractions = [D(n-k) / n for k, _, _ in draws] if n else []
        cohorts[name] = {
            "entered_positions": n,
            "observed_outcomes": observed_count,
            "censored_unknown_exits": censor_count,
            "original_censored_fraction": str(D(censor_count) / n) if n else None,
            "draws_completed": len(draws),
            "descriptive_p025_censored_fraction": _nearest_rank(censor_fractions, 25),
            "descriptive_p975_censored_fraction": _nearest_rank(censor_fractions, 975),
            "unconditional_expectancy_inference_permitted": False,
            "scenarios": scenarios,
        }
    return {
        "audit": "DECLARED_CENSOR_AWARE_ENTERED_BLOCKS_V1",
        "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC",
        "block_unit": "CONSECUTIVE_ENTERED_POSITIONS_INCLUDING_CENSORED",
        "block_length": block_length, "resamples": resamples, "seed": seed,
        "bands_are_calibrated_confidence_intervals": False,
        "costs_are_illustrative_not_broker_verified": True,
        "missing_exits_imputed": False,
        "may_select_strategy_from_result": False,
        "independent_holdout_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
        "cohorts": cohorts,
    }
