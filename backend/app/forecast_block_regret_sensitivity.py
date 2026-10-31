"""Offline fixed chronological block-omission sensitivity for paired forecast regret.

Caller must supply a frozen, nonoverlapping, causally eligible, completely
settled scored cohort. This is descriptive research, not a confidence interval
or evidence of trading profitability. No I/O, orders or notifications.
"""
import math


def audit_block_regret_sensitivity(paired_regrets, *, min_per_block=30):
    """Recompute paired mean regrets after omitting each of five fixed time blocks.

    Partition membership is set by chronological index, never by outcomes.
    This is a fragility audit; contiguous blocks are not independent draws.
    """
    if type(min_per_block) is not int or not 30 <= min_per_block <= 5000:
        raise ValueError("Invalid block support threshold")
    if type(paired_regrets) not in (tuple, list) or len(paired_regrets) > 100000:
        raise ValueError("Invalid chronological paired regret population")
    brier, log_loss = [], []
    for pair in paired_regrets:
        if type(pair) not in (tuple, list) or len(pair) != 2:
            raise ValueError("Invalid paired regret")
        a, b = pair
        if (type(a) not in (int, float) or type(b) not in (int, float) or
                not math.isfinite(a) or not math.isfinite(b) or
                abs(a) > 1 or abs(b) > 1000):
            raise ValueError("Invalid finite paired regret")
        brier.append(a)
        log_loss.append(b)

    n = len(brier)
    result = {
        "status": "DESCRIPTIVE_ONLY" if n >= 5 * min_per_block
                  else "INSUFFICIENT_CONTIGUOUS_BLOCK_SUPPORT",
        "scored": n,
        "blockCount": 5,
        "minPerBlock": min_per_block,
        "omittedBlockRanges": None,
        "retainedMeanBrierRegretBestCase": None,
        "retainedMeanBrierRegretWorstCase": None,
        "retainedMeanLogLossRegretBestCase": None,
        "retainedMeanLogLossRegretWorstCase": None,
        "sourceAuthenticated": False,
        "independentHoldoutVerified": False,
        "maySendNotification": False,
        "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
    if result["status"] != "DESCRIPTIVE_ONLY":
        return result

    # Five predeclared contiguous blocks, with remainder in the first blocks.
    # No outcome-optimized boundaries or omission choice.
    q, remainder = divmod(n, 5)
    start = 0
    brier_means, log_means, ranges = [], [], []
    for i in range(5):
        end = start + q + (i < remainder)
        retained = n - (end - start)
        brier_means.append((math.fsum(brier[:start]) + math.fsum(brier[end:])) / retained)
        log_means.append((math.fsum(log_loss[:start]) + math.fsum(log_loss[end:])) / retained)
        ranges.append({"startIndex": start, "endIndex": end - 1,
                       "omittedCount": end - start, "retainedCount": retained})
        start = end
    result.update(
        omittedBlockRanges=ranges,
        retainedMeanBrierRegretBestCase=min(brier_means),
        retainedMeanBrierRegretWorstCase=max(brier_means),
        retainedMeanLogLossRegretBestCase=min(log_means),
        retainedMeanLogLossRegretWorstCase=max(log_means),
    )
    return result
