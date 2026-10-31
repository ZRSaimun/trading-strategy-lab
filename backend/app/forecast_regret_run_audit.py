"""Disconnected chronological regret-run audit on a preselected scored cohort.

Regret is forecast loss minus causal-baseline loss, not trading P&L.
This helper cannot authenticate inputs, issue alerts or authorize orders.
"""
import math


def audit_chronological_regret_runs(paired_regrets, *, min_scored=30):
    """Worst cumulative underperformance excursion and consecutive bad runs.

    The caller must freeze a chronological nonoverlapping cohort before labels,
    establish causal baselines and verify no eligible outcomes are missing.
    Reported spans are zero-based inclusive indices into that frozen cohort,
    not wall-clock timestamps or independent market observations.
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
        "maxCumulativeBrierExcursionStartIndex": None,
        "maxCumulativeBrierExcursionEndIndex": None,
        "maxCumulativeLogLossExcursionStartIndex": None,
        "maxCumulativeLogLossExcursionEndIndex": None,
        "longestConsecutiveBrierStartIndex": None,
        "longestConsecutiveBrierEndIndex": None,
        "longestConsecutiveLogLossStartIndex": None,
        "longestConsecutiveLogLossEndIndex": None,
        "sourceAuthenticated": False, "independentHoldoutVerified": False,
        "maySendNotification": False, "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
    if status != "DESCRIPTIVE_ONLY":
        return result

    def worst_run(values):
        # Largest contiguous sum of positive *net* regret; gains inside a run
        # reduce the excursion. Zero is the floor when no bad interval exists.
        # Strict improvements retain the earliest interval when scores tie.
        current = worst = 0.0
        current_start = 0
        worst_span = None
        consecutive = longest = 0
        consecutive_start = 0
        longest_span = None
        for index, value in enumerate(values):
            candidate = current + value
            if candidate <= 0:
                current = 0.0
                current_start = index + 1
            else:
                current = candidate
                if current > worst:
                    worst = current
                    worst_span = (current_start, index)
            if value > 0:
                if consecutive == 0:
                    consecutive_start = index
                consecutive += 1
                if consecutive > longest:
                    longest = consecutive
                    longest_span = (consecutive_start, index)
            else:
                consecutive = 0
        return worst, longest, worst_span, longest_span

    for label, values in (("Brier", brier), ("LogLoss", log_loss)):
        worst, longest, excursion_span, consecutive_span = worst_run(values)
        result[f"maxCumulative{label}UnderperformanceExcursion"] = worst
        result[f"longestConsecutive{label}Underperformance"] = longest
        if excursion_span is not None:
            result[f"maxCumulative{label}ExcursionStartIndex"] = excursion_span[0]
            result[f"maxCumulative{label}ExcursionEndIndex"] = excursion_span[1]
        if consecutive_span is not None:
            result[f"longestConsecutive{label}StartIndex"] = consecutive_span[0]
            result[f"longestConsecutive{label}EndIndex"] = consecutive_span[1]
    return result
