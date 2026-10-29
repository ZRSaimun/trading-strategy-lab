"""Fixed-bin descriptive reliability on an already frozen disjoint forecast cohort.

No ingestion, I/O, model selection, notification or trading authority.
"""
from bisect import bisect_right
import math

_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)


def audit_fixed_bin_reliability(pairs, *, min_per_occupied_bin=30):
    """Five predeclared bins; sparse bins never disclose calibration estimates.

    Caller must first establish causal training, disjoint evaluation membership,
    and complete eligible outcomes. This helper does NOT verify that provenance.
    """
    if type(min_per_occupied_bin) is not int or not 30 <= min_per_occupied_bin <= 5000:
        raise ValueError("Invalid minimum bin population")
    if type(pairs) not in (list, tuple) or len(pairs) > 100000:
        raise ValueError("Invalid calibration population")
    counts = [0] * 5
    probability_sums = [0.0] * 5
    up_counts = [0] * 5
    for pair in pairs:
        if type(pair) not in (list, tuple) or len(pair) != 2:
            raise ValueError("Invalid probability/outcome pair")
        p, y = pair
        if (type(p) not in (float, int) or not math.isfinite(p) or
                not 0 < p < 1 or type(y) is not int or y not in (0, 1)):
            raise ValueError("Invalid issued probability or binary outcome")
        bucket = bisect_right(_EDGES[1:-1], p)
        counts[bucket] += 1
        probability_sums[bucket] += p
        up_counts[bucket] += y
    occupied = sum(n > 0 for n in counts)
    sparse = sum(0 < n < min_per_occupied_bin for n in counts)
    bins = []
    weighted_gap = 0.0
    for index, n in enumerate(counts):
        supported = n >= min_per_occupied_bin
        mean_p = probability_sums[index] / n if supported else None
        observed = up_counts[index] / n if supported else None
        gap = abs(mean_p - observed) if supported else None
        if gap is not None:
            weighted_gap += n * gap
        bins.append({
            "index": index, "lowerInclusive": _EDGES[index],
            "upperExclusiveExceptFinal": _EDGES[index + 1], "count": n,
            "meanIssuedProbability": mean_p, "observedUpFraction": observed,
            "absoluteCalibrationGap": gap,
        })
    status = ("INSUFFICIENT_BIN_SUPPORT" if sparse else
              "LIMITED_PROBABILITY_COVERAGE" if occupied < 2 else
              "DESCRIPTIVE_ONLY")
    return {
        "status": status, "binEdges": list(_EDGES),
        "minPerOccupiedBin": min_per_occupied_bin,
        "total": len(pairs), "occupiedBins": occupied, "sparseBins": sparse,
        "bins": bins,
        "weightedAbsoluteCalibrationGap": (
            weighted_gap / len(pairs) if status == "DESCRIPTIVE_ONLY" else None),
        "sourceAuthenticated": False, "independentHoldoutVerified": False,
        "maySendNotification": False, "mayExecutePaperOrder": False,
        "mayExecuteLiveOrder": False,
    }
