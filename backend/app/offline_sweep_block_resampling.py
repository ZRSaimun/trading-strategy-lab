"""Read-only observed-only moving-block trading-cost sensitivity; no order authority.

Resampling percentiles are descriptive, NOT calibrated confidence intervals,
independent holdout, broker quotes or proof of profitable expectancy.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal as D
from random import Random

COHORTS = ("development", "exploratory_later")
COST_BPS = (0, 5, 10, 20)


@dataclass(frozen=True)
class Trade:
    time: datetime  # source-local, unverified timezone
    cohort: str
    gross_r: D | None  # None = entered but censored, never impute
    entry: D
    risk: D


def _rank(values, numerator):
    if not values:
        return None
    values.sort()
    return str(values[max(0, (len(values) * numerator + 999) // 1000 - 1)])


def audit_observed_block_resampling(trades, *, block_length=8, resamples=500,
                                    seed=20261028):
    if type(trades) not in (list, tuple) or len(trades) > 10000:
        raise ValueError("Expected at most 10000 declared entered trades")
    if (type(block_length) is not int or not 1 <= block_length <= 10000 or
            type(resamples) is not int or not 1 <= resamples <= 1000 or
            type(seed) is not int or not 0 <= seed < 2**63):
        raise ValueError("Invalid bounded resampling parameters")
    by_cohort = {name: [] for name in COHORTS}
    previous = None
    for t in trades:
        if (not isinstance(t, Trade) or type(t.time) is not datetime or
                t.time.tzinfo is not None or t.cohort not in COHORTS or
                type(t.entry) is not D or type(t.risk) is not D or
                not t.entry.is_finite() or not t.risk.is_finite() or
                t.entry <= 0 or t.risk <= 0 or
                abs(t.entry.adjusted()) > 18 or abs(t.risk.adjusted()) > 18 or
                (t.gross_r is not None and
                 (type(t.gross_r) is not D or not t.gross_r.is_finite() or
                  abs(t.gross_r.adjusted()) > 18))):
            raise ValueError("Invalid observed/censored trade geometry")
        if previous is not None and t.time <= previous:
            raise ValueError("Trade timestamps must be strictly increasing")
        previous = t.time
        by_cohort[t.cohort].append(t)
    cohorts = {}
    for name, declared in by_cohort.items():
        observed = [t for t in declared if t.gross_r is not None]
        n = len(observed)
        if n * resamples > 2000000:
            raise ValueError("Resampling work budget exceeded")
        gross = [t.gross_r for t in observed]
        unit_cost = [t.entry / (D(10000) * t.risk) for t in observed]
        rng = Random(f"LOOP2_BLOCK_V1|{seed}|{name}")
        draws = []
        if n >= block_length:
            for _ in range(resamples):
                sample = []
                while len(sample) < n:
                    start = rng.randrange(n - block_length + 1)
                    sample.extend(range(start, start + block_length))
                sample = sample[:n]
                draws.append((sum((gross[i] for i in sample), D(0)) / n,
                              sum((unit_cost[i] for i in sample), D(0)) / n))
        scenarios = []
        for bps in COST_BPS:
            mean = (sum((g - bps*c for g, c in zip(gross, unit_cost)), D(0)) / n
                    if n else None)
            sampled = [g - bps*c for g, c in draws]
            scenarios.append({"additional_round_trip_bps": bps,
                              "observed_mean_net_r": str(mean) if mean is not None else None,
                              "descriptive_p025_mean_net_r": _rank(sampled[:], 25),
                              "descriptive_p975_mean_net_r": _rank(sampled[:], 975)})
        cohorts[name] = {"entered_positions": len(declared),
                         "observed_outcomes": n,
                         "censored_unknown_exits": len(declared)-n,
                         "resampling_available": bool(draws),
                         "unconditional_expectancy_inference_permitted": False,
                         "scenarios": scenarios}
    return {"audit": "OBSERVED_ONLY_MOVING_BLOCK_RESAMPLING_V1",
            "source_clock": "SOURCE_LOCAL_UNAUTHENTICATED_NOT_UTC",
            "block_unit": "CONSECUTIVE_OBSERVED_TRADE_INDICES_NOT_ELAPSED_TIME",
            "block_length": block_length, "resamples": resamples, "seed": seed,
            "costs_are_illustrative_not_broker_verified": True,
            "bands_are_calibrated_confidence_intervals": False,
            "may_select_strategy_from_result": False,
            "independent_holdout_verified": False,
            "verified_profitability": False, "may_execute_order": False,
            "cohorts": cohorts}
