"""Offline additive-R drawdown stress on a complete frozen M1 bracket population.

No broker fills, position compounding, archive certification or trading advice.
An independent, pre-outcome frozen registry is required for credible research.
"""
from decimal import Decimal, InvalidOperation, localcontext


_COSTS = (0, 5, 10, 20)


def _finite_decimal(value):
    if not isinstance(value, str) or len(value) > 160:
        raise ValueError('Missing or malformed exact net-R bound')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Malformed exact net-R bound') from exc
    if not number.is_finite():
        raise ValueError('Nonfinite net-R bound')
    return number


def _drawdown(returns):
    """Maximum peak-to-trough drop of an additive-R equity path (zero origin)."""
    running = peak = drawdown = Decimal(0)
    for value in returns:
        running += value
        if running > peak:
            peak = running
        if peak - running > drawdown:
            drawdown = peak - running
    return drawdown


def summarize_frozen_drawdown(population_audit):
    """Worst-case additive-R path given independently bounded trade returns.

    Max drawdown over all permitted intrabar outcomes equals max drawdown
    of the all-lower-return sequence: every peak-to-trough interval can use
    its lower bound, and earlier returns cancel from that interval's drop.
    The all-upper sequence is a comparator, NOT a minimum drawdown bound.
    """
    if not isinstance(population_audit, dict):
        raise ValueError('Population audit required')
    outcome = population_audit.get('outcome_audit')
    if not isinstance(outcome, dict):
        raise ValueError('Missing bracket outcome audit')
    counts = outcome.get('counts')
    paths = outcome.get('paths')
    if not isinstance(counts, dict) or not isinstance(paths, list):
        raise ValueError('Malformed bracket outcome audit')
    if outcome.get('total') != len(paths) or not isinstance(outcome.get('total'), int):
        raise ValueError('Inconsistent path population')
    if sum(counts.get(k, -1) for k in ('DETERMINATE', 'AMBIGUOUS', 'CENSORED')) != len(paths):
        raise ValueError('Inconsistent bracket status counts')
    if population_audit.get('complete_against_supplied_manifest') is not True:
        raise ValueError('Missing frozen population completeness assertion')
    if population_audit.get('eligible_signals') != len(paths):
        raise ValueError('Inconsistent frozen eligible population')
    if outcome.get('verified_profitability') is not False:
        raise ValueError('Unexpected profitability certification')
    scenarios = outcome.get('cost_scenarios')
    if not isinstance(scenarios, list) or len(scenarios) != len(_COSTS):
        raise ValueError('Unexpected cost scenarios')

    # No selective survivor filtering. A censored or excluded signal invalidates
    # a full-population additive-R drawdown, as does inadequate week dispersion.
    sufficient = (outcome.get('status') == 'DESCRIPTIVE_BOUNDS_ONLY'
                  and population_audit.get('declared_excluded_signals') == 0
                  and counts['CENSORED'] == 0
                  and len(paths) >= 30
                  and type(outcome.get('active_utc_weeks')) is int
                  and outcome['active_utc_weeks'] >= 12)
    if not sufficient:
        return dict(status='WITHHELD_INCOMPLETE_OR_INSUFFICIENT',
                    paths=len(paths), active_utc_weeks=outcome.get('active_utc_weeks'),
                    cost_scenarios=[], verified_profitability=False,
                    warning='No drawdown calculated from excluded, censored, or insufficient frozen populations.')

    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for index, bps in enumerate(_COSTS):
            if type(scenarios[index].get('additional_round_trip_bps')) is not int or scenarios[index]['additional_round_trip_bps'] != bps:
                raise ValueError('Cost scenario identity changed')
            lower, upper = [], []
            for row in paths:
                cost_rows = row.get('cost_scenarios')
                if not isinstance(cost_rows, list) or len(cost_rows) != len(_COSTS):
                    raise ValueError('Incomplete per-path cost scenarios')
                cost = cost_rows[index]
                if type(cost.get('additional_round_trip_bps')) is not int or cost['additional_round_trip_bps'] != bps:
                    raise ValueError('Per-path cost scenario changed')
                low, high = _finite_decimal(cost.get('lower_net_r')), _finite_decimal(cost.get('upper_net_r'))
                if low > high:
                    raise ValueError('Inverted net-R bounds')
                lower.append(low)
                upper.append(high)
            reports.append(dict(additional_round_trip_bps=bps,
                                total_lower_net_r=str(sum(lower)),
                                total_upper_net_r=str(sum(upper)),
                                maximum_possible_additive_drawdown_r=str(_drawdown(lower)),
                                all_upper_path_drawdown_r=str(_drawdown(upper))))
    return dict(status='DESCRIPTIVE_WORST_CASE_BOUNDS_ONLY',
                paths=len(paths), active_utc_weeks=outcome['active_utc_weeks'],
                cost_scenarios=reports, verified_profitability=False,
                executable_broker_fills=False,
                warning='Additive R only, not compounded equity or executable P&L. All-upper path is not a minimum-drawdown bound. No archive, holdout, cost, or fill certification.')


def audit_frozen_bracket_drawdown(manifest, paths, expected_manifest_sha256):
    """Run the existing full-population integrity gate before drawdown stress."""
    from app.frozen_bracket_population import audit_frozen_bracket_population
    result = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    return summarize_frozen_drawdown(result)
