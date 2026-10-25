"""Read-only, exact-decimal weekly fragility of a complete frozen M1 population.

Descriptive after-outcome audit only. Never a signal filter, significance test,
capital-equity curve, broker fill or permission to execute an order.
"""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext

from app.frozen_bracket_population import audit_frozen_bracket_population

_COSTS = (0, 5, 10, 20)
_MAX_WEEKS = 520


def _decimal(value):
    if not isinstance(value, str) or len(value) > 160:
        raise ValueError('Missing or malformed exact net-R bound')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Malformed exact net-R bound') from exc
    if not number.is_finite():
        raise ValueError('Nonfinite net-R bound')
    return number


def _withheld(audit, reason):
    return dict(status='WITHHELD_INCOMPLETE_OR_INSUFFICIENT',
                reason=reason, eligible_signals=audit['eligible_signals'],
                declared_excluded_signals=audit['declared_excluded_signals'],
                active_utc_weeks=audit['outcome_audit'].get('active_utc_weeks'),
                cost_scenarios=[], verified_profitability=False,
                executable_broker_fills=False)


def audit_frozen_weekly_fragility(manifest, paths, expected_manifest_sha256):
    """Conservative calendar-week sensitivity; no retrospective trade selection.

    All paths and their costs are recomputed by the upstream frozen-population
    gate. Each eligible signal is grouped by its *signal* ISO UTC week, not by
    its future exit time. Weekly results are additive R, not compounded cash.
    """
    audit = audit_frozen_bracket_population(manifest, paths, expected_manifest_sha256)
    outcome = audit['outcome_audit']
    counts = outcome['counts']
    rows = outcome['paths']
    if (audit['complete_against_supplied_manifest'] is not True
            or outcome.get('verified_profitability') is not False
            or outcome.get('executable_broker_fills') is not False
            or outcome.get('total') != len(rows)
            or len(rows) != audit['eligible_signals']
            or sum(counts[k] for k in ('DETERMINATE', 'AMBIGUOUS', 'CENSORED')) != len(rows)):
        raise ValueError('Inconsistent upstream frozen population audit')
    if (audit['declared_excluded_signals'] != 0 or counts['CENSORED'] != 0
            or outcome.get('status') != 'DESCRIPTIVE_BOUNDS_ONLY'
            or len(rows) < 30 or outcome.get('active_utc_weeks', 0) < 12):
        return _withheld(audit, 'Excluded, censored or insufficient time-dispersed frozen signals')

    # The upstream validator ensures exact one-to-one membership and identity.
    # Retain all signals, including negative and intrabar-ambiguous outcomes.
    frozen_by_id = {r['path_id']: r for r in manifest['eligible_signals']}
    weeks_by_id = {}
    for key, frozen in frozen_by_id.items():
        iso = datetime.fromtimestamp(frozen['signal_at'], timezone.utc).isocalendar()
        weeks_by_id[key] = f'{iso.year:04d}-W{iso.week:02d}'
    week_counts = defaultdict(int)
    for row in rows:
        week_counts[weeks_by_id[row['path_id']]] += 1
    if len(week_counts) != outcome['active_utc_weeks']:
        raise ValueError('Inconsistent UTC week dispersion')
    if len(week_counts) > _MAX_WEEKS:
        return _withheld(audit, 'More than 520 active UTC weeks; bounded output required')

    scenarios = outcome['cost_scenarios']
    if not isinstance(scenarios, list) or len(scenarios) != len(_COSTS):
        raise ValueError('Unexpected upstream cost scenario population')
    with localcontext() as ctx:
        ctx.prec = 80
        reports = []
        for i, bps in enumerate(_COSTS):
            if (type(scenarios[i].get('additional_round_trip_bps')) is not int
                    or scenarios[i]['additional_round_trip_bps'] != bps):
                raise ValueError('Changed cost scenario identity')
            lower = defaultdict(lambda: Decimal(0))
            upper = defaultdict(lambda: Decimal(0))
            for row in rows:
                cost_rows = row.get('cost_scenarios')
                if not isinstance(cost_rows, list) or len(cost_rows) != len(_COSTS):
                    raise ValueError('Missing per-path cost scenarios')
                cost = cost_rows[i]
                if (type(cost.get('additional_round_trip_bps')) is not int
                        or cost['additional_round_trip_bps'] != bps):
                    raise ValueError('Changed per-path cost scenario identity')
                lo, hi = _decimal(cost.get('lower_net_r')), _decimal(cost.get('upper_net_r'))
                if lo > hi:
                    raise ValueError('Inverted per-path return bounds')
                week = weeks_by_id[row['path_id']]
                lower[week] += lo
                upper[week] += hi
            if set(lower) != set(week_counts) or set(upper) != set(week_counts):
                raise ValueError('Missing weekly signal outcomes')
            low_total, high_total = sum(lower.values()), sum(upper.values())
            # These are post-hoc sensitivity diagnostics, not tradable filters.
            # Remove the single most favorable week under each respective bound.
            reports.append(dict(
                additional_round_trip_bps=bps,
                total_lower_net_r=str(low_total),
                total_upper_net_r=str(high_total),
                certainly_positive_utc_weeks=sum(lower[w] > 0 for w in week_counts),
                certainly_negative_utc_weeks=sum(upper[w] < 0 for w in week_counts),
                sign_ambiguous_utc_weeks=sum(lower[w] <= 0 <= upper[w] for w in week_counts),
                worst_week_lower_net_r=str(min(lower.values())),
                worst_week_upper_net_r=str(min(upper.values())),
                least_favorable_leave_one_week_out_lower_total_r=str(low_total - max(lower.values())),
                least_favorable_leave_one_week_out_upper_total_r=str(high_total - max(upper.values())),
            ))
    most_populated = sorted(week_counts, key=lambda w: (-week_counts[w], w))[:5]
    return dict(status='DESCRIPTIVE_WEEKLY_FRAGILITY_ONLY',
                eligible_signals=len(rows), declared_excluded_signals=0,
                active_utc_weeks=len(week_counts),
                minimum_signals_in_active_week=min(week_counts.values()),
                maximum_signals_in_active_week=max(week_counts.values()),
                most_populated_weeks=[dict(utc_iso_week=w, signals=week_counts[w]) for w in most_populated],
                cost_scenarios=reports,
                verified_profitability=False, executable_broker_fills=False,
                untouched_holdout_verified=False, externally_preregistered=False,
                warning='After-outcome weekly concentration, not an inferential confidence interval or executable return. A supplied manifest digest cannot establish pre-outcome registration, full eligibility, licensing, UTC validity, broker costs, or an untouched holdout.')
