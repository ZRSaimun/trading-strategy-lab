"""Fail-closed, read-only reconciliation of declared exploratory confluence aggregates.

This does not read candles, authenticate provenance, validate broker fills, or
establish a holdout. Never use this output as a signal or order authorization.
"""
import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path

STATES = tuple(f"FVG{f}_MSS{m}_DISP{d}" for f in (0, 1) for m in (0, 1) for d in (0, 1))
COUNT_KEYS = ("confirmed", "entered", "observed", "censored", "missing_entry", "invalid_geometry")
# This is a frozen, declared-only research report. Unknown fields must not
# silently imply stronger source, holdout, cost or execution assurances.
TOP_LEVEL_KEYS = frozenset(("protocol", "scope", "source_status", "cost_status",
                            "independent_holdout", "verified_profitability",
                            "may_execute_order", "states", "totals"))
STATE_KEYS = frozenset(("state", *COUNT_KEYS, "observed_mean_net_r_by_extra_bps"))
TOTAL_KEYS = frozenset((*COUNT_KEYS, "observed_mean_net_r_by_extra_bps"))


def _require_exact_keys(value, expected, location):
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{location}: unexpected or missing aggregate report fields")

ROUNDING_TOLERANCE = Decimal("0.00001")  # two independently rounded 5dp means
MAX_AGGREGATE_JSON_BYTES = 4_000_000


def _reject_duplicate_json_keys(pairs):
    """Do not let a later JSON key silently replace a provenance or count claim."""
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate aggregate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite_json_constant(value):
    raise ValueError(f"Nonstandard aggregate JSON numeric constant: {value}")


def _reject_overflow_json_float(token):
    """Reject JSON exponent overflow before an unused field can hide infinity.

    The closed aggregate schema does not use JSON floats for research means;
    those are five-place decimal strings. This protects the shared loader
    independently of the later schema validation.
    """
    import math

    value = float(token)
    if not math.isfinite(value):
        raise ValueError("Nonfinite aggregate JSON numeric exponent")
    return value


def load_declared_aggregate(path):
    """Bound input bytes and parse nested keys without last-write-wins ambiguity.

    This is syntactic input hygiene, not evidence that a report is authentic.
    Call audit_aggregate on the returned payload before deriving conclusions.
    """
    with Path(path).open("rb") as source:
        raw = source.read(MAX_AGGREGATE_JSON_BYTES + 1)
    if len(raw) > MAX_AGGREGATE_JSON_BYTES:
        raise ValueError("Aggregate JSON exceeds bounded input size")
    return json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=_reject_duplicate_json_keys,
        parse_constant=_reject_nonfinite_json_constant,
        parse_float=_reject_overflow_json_float,
    )


def _nonnegative_integer(value, name):
    if type(value) is not int or value < 0:
        raise ValueError(f"{name}: expected nonnegative integer")
    return value


def _mean(value, name):
    if not isinstance(value, str):
        raise ValueError(f"{name}: mean must be a decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{name}: invalid decimal") from exc
    if not result.is_finite() or result.as_tuple().exponent != -5:
        raise ValueError(f"{name}: expected finite mean rounded to exactly 5 decimal places")
    return result


def audit_aggregate(payload):
    """Reconcile counts and rounded cost means without interpreting an edge."""
    _require_exact_keys(payload, TOP_LEVEL_KEYS, "report")
    if (payload.get("protocol") != "source-local-sweep-confirmation-v3" or
            payload.get("scope") != "annual_exploratory_later_16_archives" or
            payload.get("source_status") != "UNAUTHENTICATED" or
            payload.get("cost_status") != "ILLUSTRATIVE_EXTRA_BPS_NOT_EXECUTABLE" or
            payload.get("independent_holdout") is not False or
            payload.get("verified_profitability") is not False or
            payload.get("may_execute_order") is not False):
        raise ValueError("Unsafe or unsupported research provenance/permission claim")
    rows = payload.get("states")
    if not isinstance(rows, list) or len(rows) != len(STATES):
        raise ValueError("Exactly eight fixed confluence states required")
    seen = set()
    totals = {k: 0 for k in COUNT_KEYS}
    weighted = {0: Decimal(0), 5: Decimal(0)}
    positive_cells = []
    for row in rows:
        _require_exact_keys(row, STATE_KEYS, "state")
        state = row.get("state")
        if state not in STATES or state in seen:
            raise ValueError("Unknown or duplicate confluence state")
        seen.add(state)
        counts = {k: _nonnegative_integer(row.get(k), f"{state}.{k}") for k in COUNT_KEYS}
        if counts["confirmed"] != counts["entered"] + counts["missing_entry"] + counts["invalid_geometry"]:
            raise ValueError(f"{state}: confirmed population does not reconcile")
        if counts["entered"] != counts["observed"] + counts["censored"]:
            raise ValueError(f"{state}: entered population does not reconcile")
        for k in COUNT_KEYS:
            totals[k] += counts[k]
        means = row.get("observed_mean_net_r_by_extra_bps")
        if not isinstance(means, dict) or set(means) != {"0", "5"}:
            raise ValueError(f"{state}: expected 0/5-bps observed means")
        if counts["observed"] == 0:
            if means["0"] is not None or means["5"] is not None:
                raise ValueError(f"{state}: empty observed cohort cannot have a mean")
            continue
        gross = _mean(means["0"], f"{state}.0bps")
        cost5 = _mean(means["5"], f"{state}.5bps")
        if cost5 > gross:
            raise ValueError(f"{state}: adding costs improved mean return")
        weighted[0] += gross * counts["observed"]
        weighted[5] += cost5 * counts["observed"]
        if cost5 > 0:
            positive_cells.append({"state": state, "observed": counts["observed"],
                                   "mean_net_r_at_5bps": str(cost5),
                                   "sparse_under_30": counts["observed"] < 30})
    if seen != set(STATES):
        raise ValueError("Missing confluence state")
    declared = payload.get("totals")
    _require_exact_keys(declared, TOTAL_KEYS, "totals")
    for k, v in totals.items():
        if _nonnegative_integer(declared.get(k), f"totals.{k}") != v:
            raise ValueError(f"Total {k} does not reconcile")
    if not totals["observed"]:
        raise ValueError("No observed outcomes to audit")
    reported = declared.get("observed_mean_net_r_by_extra_bps")
    if not isinstance(reported, dict) or set(reported) != {"0", "5"}:
        raise ValueError("Expected 0/5-bps overall means")
    overall = {}
    for bps in (0, 5):
        computed = weighted[bps] / totals["observed"]
        declared_mean = _mean(reported[str(bps)], f"totals.{bps}bps")
        if abs(computed - declared_mean) > ROUNDING_TOLERANCE:
            raise ValueError(f"Overall {bps}-bps mean does not reconcile with states")
        overall[str(bps)] = str(computed.quantize(Decimal("0.00000001")))
    return {
        "audit": "PASS_DECLARED_AGGREGATE_ARITHMETIC_ONLY",
        "population": "ANNUAL_EXPLORATORY_LATER_ALREADY_INSPECTED",
        "counts": totals,
        "reconstructed_observed_mean_net_r_by_extra_bps": overall,
        "positive_observed_cells_at_5bps": positive_cells,
        "positive_cell_selection_is_retrospective": True,
        "censored_outcomes_not_imputed": totals["censored"],
        "independent_holdout_verified": False,
        "source_authenticated": False,
        "executable_broker_costs_verified": False,
        "verified_profitability": False,
        "may_execute_order": False,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("aggregate_json", type=Path)
    args = parser.parse_args(argv)
    result = audit_aggregate(load_declared_aggregate(args.aggregate_json))
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
