"""Disconnected chronological regret-run audit on a preselected scored cohort.

Regret is forecast loss minus causal-baseline loss, not trading P&L.
This helper cannot authenticate inputs, issue alerts or authorize orders.
"""
import math


def audit_chronological_regret_runs(paired_regrets, *, min_scored=30):
    """Worst cumulative underperformance excursion and consecutive bad runs.

    The caller must freeze a chronological nonoverlapping cohort before labels,
    establish causal baselines and verify no eligible outcomes are missing.
    """
    if type(min_scored) is not int or not 30 <= min_scored <= 5000:
        raise ValueError("Invalid minimum scored population")
    if type(paired_regrets) not in (tuple, list) or len(paired_regrets) > 100000:
        raise ValueError("Invalid chronological regret population")
    brier = []
    log_loss = []
    for pair in paired_regrets:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise ValueError("Invalid paired regret")
        a, b = pair
        if (type(a) not in (int, float) or type(b) not in (int, float) or
                abs(a) > 1 or abs(b) > 1000 or
                not math.isfinite(a) or not math.isfinite(b)):
            raise ValueError("Invalid finite paired regret")
        brier.append(a)
        log_loss.append(b)

    status = "DESCRIPTIVE_ONLY" if len(paired_regrets) >= min_scored else "INSUFFICIENT_DISJOINT_SCORES"
    result = {
        "status": status, "scored": len(paired_regrets),
        "maxCumulativeBrierUnderperformanceExcursion": None,
        "maxCumulativeLogLossUnderperformanceExcursion": None,
        "longestConsecutiveBrierUnderperformance": None,
        "longestConsecutiveLogLossUnderperformance": None,
        "sourceAuthenticated": False, "independentHoldoutVerified": False,
        "maySendNotification": False, "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
    if status != "DESCRIPTIVE_ONLY":
        return result

    def worst_run(values):
        # Largest contiguous sum of positive *net* regret; gains inside a run
        # reduce the excursion. Zero is the floor when no bad interval exists.
        current = worst = 0.0
        consecutive = longest = 0
        for value in values:
            current = max(0.0, current + value)
            worst = max(worst, current)
            consecutive = consecutive + 1 if value > 0 else 0
            longest = max(longest, consecutive)
        return worst, longest

    result["maxCumulativeBrierUnderperformanceExcursion"], result[
        "longestConsecutiveBrierUnderperformance"] = worst_run(brier)
    result["maxCumulativeLogLossUnderperformanceExcursion"], result[
        "longestConsecutiveLogLossUnderperformance"] = worst_run(log_loss)
    return result
