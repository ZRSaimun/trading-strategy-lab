"""Read-only, source-local M1 liquidity-sweep research. NOT broker backtesting.

The clock has NO verified timezone. No BID/ASK executable fills, financing,
slippage or venue provenance. Outputs are exploratory and cannot authorize orders.
"""
import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
from zipfile import ZipFile

Q = Decimal
STEP = timedelta(minutes=1)
BAR_STEP = timedelta(minutes=15)
VOLATILITY_REGIMES = ("LOW_LT_10_BPS", "MID_10_TO_LT_30_BPS", "HIGH_GTE_30_BPS")
SIGNAL_DIRECTIONS = ("LONG_SWEEP_LOW", "SHORT_SWEEP_HIGH")
CONFLUENCE_STATES = tuple(
    f"FVG{fvg}_MSS{mss}_DISP{disp}"
    for fvg in (0, 1) for mss in (0, 1) for disp in (0, 1))
CONFIRMATION_FVG_STATES = ("SAME_DIRECTION_THREE_CANDLE_FVG",
                           "NO_SAME_DIRECTION_THREE_CANDLE_FVG")
CONFIRMATION_STRUCTURE_STATES = ("CONFIRMATION_CLOSE_BREAKS_PRIOR_RANGE",
                                 "NO_CONFIRMATION_CLOSE_BREAK_OF_PRIOR_RANGE")
CONFIRMATION_DISPLACEMENT_STATES = (
    "DIRECTIONAL_BODY_GTE_PRIOR_MEDIAN_RANGE",
    "NO_DIRECTIONAL_BODY_GTE_PRIOR_MEDIAN_RANGE")


def prior_range_regime(prior_bars):
    """Frozen ex-ante range bin; only bars before the sweep are inspected."""
    if not prior_bars:
        raise ValueError("Missing pre-signal range observations")
    ranges = sorted(Q(10000) * (b.h - b.l) / b.c for b in prior_bars)
    mid = len(ranges) // 2
    median_bps = (ranges[mid] if len(ranges) % 2 else
                  (ranges[mid - 1] + ranges[mid]) / Q(2))
    if median_bps < Q(10):
        return VOLATILITY_REGIMES[0]
    if median_bps < Q(30):
        return VOLATILITY_REGIMES[1]
    return VOLATILITY_REGIMES[2]


def confirmation_displacement_state(prior_bars, confirmation, is_long):
    """Causal body-size proxy, measured only at completed confirmation.

    Require a directional body, at least as large as the median completed
    pre-sweep high-low range. This is NOT an ICT displacement validation,
    broker signal, or candidate filter. Equality is included.
    """
    if not prior_bars:
        raise ValueError("Missing pre-sweep range observations")
    ranges = sorted(b.h - b.l for b in prior_bars)
    mid = len(ranges) // 2
    median_range = (ranges[mid] if len(ranges) % 2 else
                    (ranges[mid - 1] + ranges[mid]) / Q(2))
    body = (confirmation.c - confirmation.o if is_long else
            confirmation.o - confirmation.c)
    return CONFIRMATION_DISPLACEMENT_STATES[
        0 if body > 0 and body >= median_range else 1]


@dataclass(frozen=True)
class Bar:
    time: datetime
    o: Decimal
    h: Decimal
    l: Decimal
    c: Decimal
    segment: int


def read_archive(path):
    """Stream a HistData ASCII M1 ZIP without extracting or assuming UTC."""
    path = Path(path)
    sha = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            sha.update(chunk)
    candles = []
    quality = {"m1_rows": 0, "discontinuities": 0, "backward_jumps": 0,
               "discarded_partial_15m": 0, "complete_15m": 0}
    with ZipFile(path) as z:
        members = [i for i in z.infolist() if i.filename.lower().endswith(".csv")]
        if len(members) != 1 or "/" in members[0].filename or "\\" in members[0].filename:
            raise ValueError("Expected exactly one flat CSV member")
        if members[0].file_size > 500_000_000:
            raise ValueError("Archive member too large")
        name = members[0].filename
        if not (name.startswith("DAT_ASCII_") and "_M1_" in name):
            raise ValueError("Unexpected HistData member name")
        current, current_key, prev = [], None, None
        segment = 0

        def flush():
            if not current:
                return
            if len(current) == 15 and current[0][0].minute % 15 == 0:
                candles.append(Bar(current[0][0], current[0][1],
                                   max(r[2] for r in current),
                                   min(r[3] for r in current), current[-1][4], segment))
                quality["complete_15m"] += 1
            else:
                quality["discarded_partial_15m"] += 1

        with z.open(members[0]) as stream:
            for line_number, raw in enumerate(stream, 1):
                try:
                    fields = raw.decode("ascii").strip().split(";")
                    if len(fields) != 6:
                        raise ValueError("field count")
                    stamp = datetime.strptime(fields[0], "%Y%m%d %H%M%S")
                    if stamp.second != 0:
                        raise ValueError("unaligned minute")
                    o, h, l, c = map(Q, fields[1:5])
                    volume = Q(fields[5])
                    if not all(v.is_finite() and v > 0 for v in (o, h, l, c)):
                        raise ValueError("nonpositive or nonfinite OHLC")
                    if not volume.is_finite() or volume < 0:
                        raise ValueError("invalid volume")
                    if h < max(o, c) or l > min(o, c) or l > h:
                        raise ValueError("invalid OHLC")
                except Exception as exc:
                    raise ValueError(f"Invalid M1 row {line_number}") from exc
                quality["m1_rows"] += 1
                if prev is not None and stamp - prev != STEP:
                    flush()
                    current = []
                    current_key = None
                    segment += 1
                    quality["discontinuities"] += 1
                    if stamp <= prev:
                        quality["backward_jumps"] += 1
                key = (stamp.year, stamp.month, stamp.day, stamp.hour, stamp.minute // 15)
                if current_key is not None and key != current_key:
                    flush()
                    current = []
                current_key = key
                current.append((stamp, o, h, l, c))
                prev = stamp
        flush()  # ZIP CRC is checked by reading through to EOF.
    return candles, dict(quality, zip_sha256=sha.hexdigest(), member=name,
                         timezone="UNVERIFIED_SOURCE_LOCAL", bid_ask="UNVERIFIED")


def research(bars, *, lookback=16, horizon=16, embargo=16):
    """Frozen sweep/reclaim + next-bar displacement; next-open entry.

    Chronological 70/30 exploratory split, no hyperparameter search. Stops win
    same-bar stop/target collisions. Missing observations censor entered
    outcomes; confirmed signals without a verifiable entry are counted apart.
    """
    if not (lookback >= 2 and horizon >= 1 and embargo >= horizon):
        raise ValueError("Invalid frozen research protocol")
    split = len(bars) * 7 // 10
    cohorts = {"development": [], "exploratory_later": []}
    censored = {"development": 0, "exploratory_later": 0}
    # Entered but censored positions have known entry/stop geometry, even
    # though no exit was observed. Retain it for explicitly hypothetical
    # missing-outcome stress, never as an invented execution or fill.
    censored_entry_risks = {"development": [], "exploratory_later": []}
    confirmed = {"development": 0, "exploratory_later": 0}
    invalid_entry_geometry = {"development": 0, "exploratory_later": 0}
    entered = {"development": 0, "exploratory_later": 0}
    # A confirmed signal must not vanish from the sample simply because its
    # *future* entry bar is missing, crosses a source gap, or enters embargo.
    # These have no observable fill and must not be counted as entered trades.
    entry_unobservable = {"development": 0, "exploratory_later": 0}
    # Every *observed* exit has exactly one frozen path classification.
    # These describe source OHLC proxy paths, never actual broker fills.
    exit_path_counts = {
        name: {"stop_touch_without_adverse_open": 0,
               "stop_touch_with_adverse_open": 0,
               "target_touch": 0, "horizon_close": 0}
        for name in cohorts
    }
    adverse_open_extra_loss_r = {name: [] for name in cohorts}
    # Count only source-contiguous 15m candles actually inspected after entry.
    # Missing exits have an observed prefix, not an invented total holding time.
    observed_holding_bars = {name: [] for name in cohorts}
    censored_observed_prefix_bars = {name: [] for name in cohorts}
    # A single OHLC candle may touch both barriers. Source opens distinguish
    # immediate stop/target crossings from unknown intrabar ordering; none
    # establishes a broker fill or changes the frozen stop-first outcomes.
    same_bar_collision = {
        name: {"opens_at_or_beyond_stop": 0,
               "opens_at_or_beyond_target": 0,
               "opens_between_barriers_order_unknown": 0}
        for name in cohorts
    }
    # Classify every confirmed signal from strictly pre-sweep bars, even if
    # its future entry/exit is unobservable. No regime can filter admissions.
    volatility = {
        name: {regime: {"confirmed": 0, "entered": 0, "observed": [],
                        "censored": 0, "missing_entry": 0, "invalid": 0}
               for regime in VOLATILITY_REGIMES}
        for name in cohorts
    }
    # Direction is known at completed confirmation, not inferred from exit.
    # Preserve missing-entry and censored populations for attrition accounting.
    directions = {
        name: {side: {"confirmed": 0, "entered": 0, "observed": [],
                     "censored": 0, "missing_entry": 0, "invalid": 0}
               for side in SIGNAL_DIRECTIONS}
        for name in cohorts
    }
    # Three fully completed candles: last prior bar, sweep, confirmation.
    # A wick gap between the first and third candle is a descriptive
    # same-direction FVG approximation, not a future-touch or entry filter.
    fvg = {
        name: {state: {"confirmed": 0, "entered": 0, "observed": [],
                      "censored": 0, "missing_entry": 0, "invalid": 0}
               for state in CONFIRMATION_FVG_STATES}
        for name in cohorts
    }
    # Minimal MSS-like completed-confirmation range-break proxy. This is not
    # a pivot/structure algorithm and cannot be used to select trades.
    structure = {
        name: {state: {"confirmed": 0, "entered": 0, "observed": [],
                      "censored": 0, "missing_entry": 0, "invalid": 0}
               for state in CONFIRMATION_STRUCTURE_STATES}
        for name in cohorts
    }
    # Completed-confirmation directional body vs prior median full range.
    # Fixed ex-ante descriptive threshold; never changes trade admission.
    displacement = {
        name: {state: {"confirmed": 0, "entered": 0, "observed": [],
                      "censored": 0, "missing_entry": 0, "invalid": 0}
               for state in CONFIRMATION_DISPLACEMENT_STATES}
        for name in cohorts
    }
    # All eight joint states are descriptive; never filter admissions.
    confluence = {
        name: {key: {"confirmed": 0, "entered": 0, "observed": [],
                     "censored": 0, "missing_entry": 0, "invalid": 0}
               for key in CONFLUENCE_STATES}
        for name in cohorts
    }
    next_free = 0
    for i in range(lookback, len(bars) - 1):
        # The completed confirmation must also be inside the selected cohort;
        # a sweep immediately before embargo cannot borrow its confirmation.
        cohort = ("development" if i + 1 < split - embargo else
                  "exploratory_later" if i >= split + embargo else None)
        if cohort is None or i < next_free:
            continue
        # Only lookback, sweep and completed confirmation may establish the
        # signal. Validating the *future entry bar* here silently dropped
        # confirmed signals whenever entry data was missing (selection bias).
        window = bars[i-lookback:i+2]
        if any(x.segment != window[0].segment for x in window):
            continue
        if any(b.time-a.time != BAR_STEP for a, b in zip(window, window[1:])):
            continue
        previous_high = max(b.h for b in window[:lookback])
        previous_low = min(b.l for b in window[:lookback])
        sweep = bars[i]
        both = sweep.h > previous_high and sweep.l < previous_low
        if both:
            continue
        is_long = sweep.l < previous_low and sweep.c > previous_low
        is_short = sweep.h > previous_high and sweep.c < previous_high
        if not (is_long or is_short):
            continue
        confirmation = bars[i+1]
        if is_long and confirmation.c <= sweep.h:
            continue
        if is_short and confirmation.c >= sweep.l:
            continue
        confirmed[cohort] += 1
        direction = directions[cohort][
            "LONG_SWEEP_LOW" if is_long else "SHORT_SWEEP_HIGH"]
        direction["confirmed"] += 1
        regime = volatility[cohort][prior_range_regime(window[:lookback])]
        regime["confirmed"] += 1
        # No future entry/exit candle may affect this classification.
        prior = window[lookback - 1]
        same_direction_fvg = (
            confirmation.l > prior.h if is_long else confirmation.h < prior.l)
        fvg_cell = fvg[cohort][CONFIRMATION_FVG_STATES[
            0 if same_direction_fvg else 1]]
        fvg_cell["confirmed"] += 1
        # Both range bounds come exclusively from completed pre-sweep bars.
        # The completed confirmation is known before the following-open entry.
        range_break = (confirmation.c > previous_high if is_long else
                       confirmation.c < previous_low)
        structure_cell = structure[cohort][CONFIRMATION_STRUCTURE_STATES[
            0 if range_break else 1]]
        structure_cell["confirmed"] += 1
        displacement_cell = displacement[cohort][confirmation_displacement_state(
            window[:lookback], confirmation, is_long)]
        displacement_cell["confirmed"] += 1
        displacement_present = (
            displacement_cell is displacement[cohort][CONFIRMATION_DISPLACEMENT_STATES[0]])
        confluence_key = (f"FVG{int(same_direction_fvg)}_"
                          f"MSS{int(range_break)}_DISP{int(displacement_present)}")
        confluence_cell = confluence[cohort][confluence_key]
        confluence_cell["confirmed"] += 1
        entry_index = i + 2
        if (entry_index >= len(bars) or
                bars[entry_index].segment != confirmation.segment or
                bars[entry_index].time - confirmation.time != BAR_STEP or
                (cohort == "development" and entry_index >= split - embargo) or
                (cohort == "exploratory_later" and entry_index < split + embargo)):
            entry_unobservable[cohort] += 1
            direction["missing_entry"] += 1
            regime["missing_entry"] += 1
            fvg_cell["missing_entry"] += 1
            structure_cell["missing_entry"] += 1
            displacement_cell["missing_entry"] += 1
            confluence_cell["missing_entry"] += 1
            # No entry observation means no demonstrated position exposure.
            # Do not manufacture a fill, return or position reservation.
            continue
        entry = bars[entry_index].o
        stop = sweep.l if is_long else sweep.h
        risk = entry - stop if is_long else stop - entry
        if risk <= 0:
            invalid_entry_geometry[cohort] += 1
            direction["invalid"] += 1
            regime["invalid"] += 1
            fvg_cell["invalid"] += 1
            structure_cell["invalid"] += 1
            displacement_cell["invalid"] += 1
            confluence_cell["invalid"] += 1
            continue
        target = entry + 2*risk if is_long else entry - 2*risk
        if target <= 0:
            invalid_entry_geometry[cohort] += 1
            direction["invalid"] += 1
            regime["invalid"] += 1
            fvg_cell["invalid"] += 1
            structure_cell["invalid"] += 1
            displacement_cell["invalid"] += 1
            confluence_cell["invalid"] += 1
            continue
        entered[cohort] += 1
        direction["entered"] += 1
        regime["entered"] += 1
        fvg_cell["entered"] += 1
        structure_cell["entered"] += 1
        displacement_cell["entered"] += 1
        confluence_cell["entered"] += 1
        outcome = None
        observed_prefix = 0
        last = min(entry_index + horizon, len(bars))
        for j in range(entry_index, last):
            b = bars[j]
            if (b.segment != bars[entry_index].segment or
                    (j > entry_index and b.time - bars[j-1].time != BAR_STEP) or
                    (j >= split - embargo and cohort == "development") or
                    (j < split + embargo and cohort == "exploratory_later")):
                break
            observed_prefix += 1
            stopped = b.l <= stop if is_long else b.h >= stop
            won = b.h >= target if is_long else b.l <= target
            if stopped:
                if won:
                    if (b.o <= stop if is_long else b.o >= stop):
                        same_bar_collision[cohort]["opens_at_or_beyond_stop"] += 1
                    elif (b.o >= target if is_long else b.o <= target):
                        same_bar_collision[cohort]["opens_at_or_beyond_target"] += 1
                    else:
                        same_bar_collision[cohort][
                            "opens_between_barriers_order_unknown"] += 1
                # A source OHLC bar can open beyond the stop while remaining
                # timestamp-contiguous. Crediting an exact -1R stop in that
                # case would erase observed adverse gap risk. Use the worse
                # source open as a *hypothetical proxy*, not an executable fill
                # or a bound on broker slippage. Stop still wins same-bar ties.
                adverse_open = (b.o < stop if is_long else b.o > stop)
                exit_proxy = b.o if adverse_open else stop
                outcome = ((exit_proxy-entry)/risk if is_long
                           else (entry-exit_proxy)/risk)
                if adverse_open:
                    exit_path_counts[cohort]["stop_touch_with_adverse_open"] += 1
                    adverse_open_extra_loss_r[cohort].append(
                        abs(exit_proxy - stop) / risk)
                else:
                    exit_path_counts[cohort]["stop_touch_without_adverse_open"] += 1
                next_free = j + 1
                break
            if won:
                outcome = Q(2)
                exit_path_counts[cohort]["target_touch"] += 1
                next_free = j + 1
                break
        else:
            if last - entry_index == horizon:
                last_close = bars[last-1].c
                outcome = (last_close-entry)/risk if is_long else (entry-last_close)/risk
                exit_path_counts[cohort]["horizon_close"] += 1
                next_free = last
        if outcome is None:
            censored[cohort] += 1
            direction["censored"] += 1
            regime["censored"] += 1
            fvg_cell["censored"] += 1
            structure_cell["censored"] += 1
            displacement_cell["censored"] += 1
            confluence_cell["censored"] += 1
            censored_entry_risks[cohort].append((entry, risk))
            censored_observed_prefix_bars[cohort].append(observed_prefix)
            # A censored position has no observed exit. Do not admit another
            # hypothetical position inside its entire reserved holding window.
            # This is an analysis-only exclusion, not proof of a flat account.
            next_free = max(next_free, entry_index + horizon)
        else:
            direction["observed"].append((outcome, entry, risk))
            regime["observed"].append((outcome, entry, risk))
            fvg_cell["observed"].append((outcome, entry, risk))
            structure_cell["observed"].append((outcome, entry, risk))
            displacement_cell["observed"].append((outcome, entry, risk))
            confluence_cell["observed"].append((outcome, entry, risk))
            cohorts[cohort].append((outcome, entry, risk))
            observed_holding_bars[cohort].append(observed_prefix)
    reports = {}
    with localcontext() as ctx:
        ctx.prec = 60
        for name, trades in cohorts.items():
            if entered[name] != censored[name] + len(trades):
                raise RuntimeError("Entered-position outcome census mismatch")
            if sum(exit_path_counts[name].values()) != len(trades):
                raise RuntimeError("Observed exit-path census mismatch")
            if (exit_path_counts[name]["stop_touch_with_adverse_open"] !=
                    len(adverse_open_extra_loss_r[name])):
                raise RuntimeError("Adverse source-open loss census mismatch")
            if censored[name] != len(censored_entry_risks[name]):
                raise RuntimeError("Censored-entry risk census mismatch")
            if len(observed_holding_bars[name]) != len(trades):
                raise RuntimeError("Observed holding-duration census mismatch")
            if len(censored_observed_prefix_bars[name]) != censored[name]:
                raise RuntimeError("Censored observed-prefix census mismatch")
            if any(not 1 <= n <= horizon for n in observed_holding_bars[name]):
                raise RuntimeError("Invalid observed holding duration")
            if any(not 0 <= n < horizon for n in censored_observed_prefix_bars[name]):
                raise RuntimeError("Invalid censored observed prefix")
            collisions = same_bar_collision[name]
            if sum(collisions.values()) > (
                    exit_path_counts[name]["stop_touch_without_adverse_open"] +
                    exit_path_counts[name]["stop_touch_with_adverse_open"]):
                raise RuntimeError("Same-bar collision exceeds observed stops")
            if confirmed[name] != (entry_unobservable[name] +
                                   invalid_entry_geometry[name] + entered[name]):
                raise RuntimeError("Confirmed-signal census mismatch")
            # Frozen uncensored cohort: mean net R is linear in additional
            # round-trip bps. The zero-crossing is a descriptive cost budget,
            # never a measured spread or an executable profitability claim.
            gross_sum = sum((r for r, _, _ in trades), Q(0))
            notional_r_sum = sum((abs(entry) / risk for _, entry, risk in trades), Q(0))
            mean_gross_r = gross_sum / len(trades) if trades else None
            cost_slope = (notional_r_sum / Q(10000) / len(trades)
                          if trades else None)
            break_even_bps = (gross_sum * Q(10000) / notional_r_sum
                              if trades and gross_sum > 0 else None)
            # This is NOT a lower bound: missing exits can be arbitrarily
            # worse than any chosen -R penalty, especially across gaps.
            # Only positions with observed entry/risk are eligible; missing
            # entries and invalid stop geometry are never imputed.
            censored_cost_notional = sum(
                (abs(entry) / risk for entry, risk in censored_entry_risks[name]), Q(0))
            censored_loss_stress = []
            for assumed_loss_r in (1, 3, 5):
                for stress_bps in (0, 5, 10, 20):
                    stress_sum = (gross_sum - Q(assumed_loss_r) * censored[name]
                                  - Q(stress_bps) / Q(10000) *
                                  (notional_r_sum + censored_cost_notional))
                    censored_loss_stress.append(dict(
                        assumed_loss_per_censored_entered_r=str(-Q(assumed_loss_r)),
                        additional_round_trip_bps=stress_bps,
                        entered_population=entered[name],
                        observed_outcomes=len(trades),
                        censored_entered_outcomes=censored[name],
                        mean_net_r_if_assumption=str(stress_sum / entered[name])
                        if entered[name] else None,
                        sum_net_r_if_assumption=str(stress_sum),
                        interpretation="ILLUSTRATIVE_MISSING_EXIT_STRESS_NOT_A_LOWER_BOUND"))
            cases = []
            for bps in (0, 5, 10, 20):
                net = [r - abs(entry)*Q(bps)/Q(10000)/risk for r, entry, risk in trades]
                cases.append(dict(additional_round_trip_bps=bps, count=len(net),
                                  mean_net_r=str(sum(net, Q(0))/len(net)) if net else None,
                                  sum_net_r=str(sum(net, Q(0))),
                                  strictly_positive=sum(v > 0 for v in net)))
            # The additional charge is per *observed* contiguous 15m source
            # candle, not a broker overnight financing rate. Unknown censored
            # holding times are intentionally excluded from these means.
            time_cost_scenarios = []
            for per_bar_bps in (Q("0"), Q("0.05"), Q("0.2")):
                total = sum((r - abs(entry) / risk *
                             (Q(5) + per_bar_bps * Q(holding)) / Q(10000)
                             for (r, entry, risk), holding in zip(
                                 trades, observed_holding_bars[name])), Q(0))
                time_cost_scenarios.append(dict(
                    additional_round_trip_bps=5,
                    illustrative_additional_bps_per_observed_15m_bar=str(per_bar_bps),
                    observed_outcomes=len(trades),
                    sum_net_r=str(total),
                    mean_net_r=str(total / len(trades)) if trades else None,
                    interpretation="SOURCE_BAR_TIME_COST_SENSITIVITY_NOT_BROKER_FINANCING"))
            regime_report = {}
            for key, cell in volatility[name].items():
                observed = cell["observed"]
                if cell["confirmed"] != (cell["missing_entry"] + cell["invalid"] +
                                         cell["entered"]):
                    raise RuntimeError("Volatility signal census mismatch")
                if cell["entered"] != cell["censored"] + len(observed):
                    raise RuntimeError("Volatility entered census mismatch")
                regime_cases = []
                for bps in (0, 5, 10, 20):
                    total = sum((r - abs(entry) * Q(bps) / Q(10000) / risk
                                 for r, entry, risk in observed), Q(0))
                    regime_cases.append(dict(
                        additional_round_trip_bps=bps,
                        observed_outcomes=len(observed),
                        mean_net_r=str(total / len(observed)) if observed else None))
                regime_report[key] = dict(
                    confirmed_signals=cell["confirmed"],
                    confirmed_signals_without_observable_entry=cell["missing_entry"],
                    invalid_entry_stop_or_target_geometry=cell["invalid"],
                    entered_positions=cell["entered"],
                    observed_outcomes=len(observed),
                    censored_entered_outcomes=cell["censored"],
                    observed_only_cost_scenarios=regime_cases)
            for kind, expected in (
                ("confirmed", confirmed[name]), ("entered", entered[name]),
                ("missing_entry", entry_unobservable[name]),
                ("invalid", invalid_entry_geometry[name]),
                ("censored", censored[name])):
                if sum(cell[kind] for cell in volatility[name].values()) != expected:
                    raise RuntimeError("Volatility population reconciliation failed")
            if sum(len(cell["observed"]) for cell in volatility[name].values()) != len(trades):
                raise RuntimeError("Volatility observed population mismatch")
            direction_report = {}
            for side, cell in directions[name].items():
                observed = cell["observed"]
                if cell["confirmed"] != (cell["missing_entry"] + cell["invalid"] +
                                         cell["entered"]):
                    raise RuntimeError("Direction signal census mismatch")
                if cell["entered"] != cell["censored"] + len(observed):
                    raise RuntimeError("Direction entered census mismatch")
                side_cases = []
                for bps in (0, 5, 10, 20):
                    total = sum((r - abs(entry) * Q(bps) / Q(10000) / risk
                                 for r, entry, risk in observed), Q(0))
                    side_cases.append(dict(
                        additional_round_trip_bps=bps,
                        observed_outcomes=len(observed),
                        mean_net_r=str(total / len(observed)) if observed else None))
                direction_report[side] = dict(
                    confirmed_signals=cell["confirmed"],
                    confirmed_signals_without_observable_entry=cell["missing_entry"],
                    invalid_entry_stop_or_target_geometry=cell["invalid"],
                    entered_positions=cell["entered"],
                    observed_outcomes=len(observed),
                    censored_entered_outcomes=cell["censored"],
                    observed_only_cost_scenarios=side_cases)
            for kind, expected in (
                ("confirmed", confirmed[name]), ("entered", entered[name]),
                ("missing_entry", entry_unobservable[name]),
                ("invalid", invalid_entry_geometry[name]),
                ("censored", censored[name])):
                if sum(cell[kind] for cell in directions[name].values()) != expected:
                    raise RuntimeError("Direction population reconciliation failed")
            if sum(len(cell["observed"]) for cell in directions[name].values()) != len(trades):
                raise RuntimeError("Direction observed population mismatch")
            fvg_report = {}
            for state, cell in fvg[name].items():
                observed = cell["observed"]
                if cell["confirmed"] != (cell["missing_entry"] + cell["invalid"] +
                                         cell["entered"]):
                    raise RuntimeError("FVG signal census mismatch")
                if cell["entered"] != cell["censored"] + len(observed):
                    raise RuntimeError("FVG entered census mismatch")
                fvg_cases = []
                for bps in (0, 5, 10, 20):
                    total = sum((r - abs(entry) * Q(bps) / Q(10000) / risk
                                 for r, entry, risk in observed), Q(0))
                    fvg_cases.append(dict(
                        additional_round_trip_bps=bps,
                        observed_outcomes=len(observed),
                        mean_net_r=str(total / len(observed)) if observed else None))
                fvg_report[state] = dict(
                    confirmed_signals=cell["confirmed"],
                    confirmed_signals_without_observable_entry=cell["missing_entry"],
                    invalid_entry_stop_or_target_geometry=cell["invalid"],
                    entered_positions=cell["entered"],
                    observed_outcomes=len(observed),
                    censored_entered_outcomes=cell["censored"],
                    observed_only_cost_scenarios=fvg_cases)
            for kind, expected in (
                ("confirmed", confirmed[name]), ("entered", entered[name]),
                ("missing_entry", entry_unobservable[name]),
                ("invalid", invalid_entry_geometry[name]),
                ("censored", censored[name])):
                if sum(cell[kind] for cell in fvg[name].values()) != expected:
                    raise RuntimeError("FVG population reconciliation failed")
            if sum(len(cell["observed"]) for cell in fvg[name].values()) != len(trades):
                raise RuntimeError("FVG observed population mismatch")
            structure_report = {}
            for state, cell in structure[name].items():
                observed = cell["observed"]
                if cell["confirmed"] != (cell["missing_entry"] + cell["invalid"] +
                                         cell["entered"]):
                    raise RuntimeError("Structure signal census mismatch")
                if cell["entered"] != cell["censored"] + len(observed):
                    raise RuntimeError("Structure entered census mismatch")
                structure_cases = []
                for bps in (0, 5, 10, 20):
                    total = sum((r - abs(entry) * Q(bps) / Q(10000) / risk
                                 for r, entry, risk in observed), Q(0))
                    structure_cases.append(dict(
                        additional_round_trip_bps=bps,
                        observed_outcomes=len(observed),
                        mean_net_r=str(total / len(observed)) if observed else None))
                structure_report[state] = dict(
                    confirmed_signals=cell["confirmed"],
                    confirmed_signals_without_observable_entry=cell["missing_entry"],
                    invalid_entry_stop_or_target_geometry=cell["invalid"],
                    entered_positions=cell["entered"],
                    observed_outcomes=len(observed),
                    censored_entered_outcomes=cell["censored"],
                    observed_only_cost_scenarios=structure_cases)
            for kind, expected in (
                ("confirmed", confirmed[name]), ("entered", entered[name]),
                ("missing_entry", entry_unobservable[name]),
                ("invalid", invalid_entry_geometry[name]),
                ("censored", censored[name])):
                if sum(cell[kind] for cell in structure[name].values()) != expected:
                    raise RuntimeError("Structure population reconciliation failed")
            if sum(len(cell["observed"]) for cell in structure[name].values()) != len(trades):
                raise RuntimeError("Structure observed population mismatch")
            displacement_report = {}
            for state, cell in displacement[name].items():
                observed = cell["observed"]
                if cell["confirmed"] != (cell["missing_entry"] + cell["invalid"] +
                                          cell["entered"]):
                    raise RuntimeError("Displacement signal census mismatch")
                if cell["entered"] != cell["censored"] + len(observed):
                    raise RuntimeError("Displacement entered census mismatch")
                cost_cases = []
                for bps in (0, 5, 10, 20):
                    total = sum((r - abs(entry) * Q(bps) / Q(10000) / risk
                                 for r, entry, risk in observed), Q(0))
                    cost_cases.append(dict(
                        additional_round_trip_bps=bps,
                        observed_outcomes=len(observed),
                        mean_net_r=str(total / len(observed)) if observed else None))
                displacement_report[state] = dict(
                    confirmed_signals=cell["confirmed"],
                    confirmed_signals_without_observable_entry=cell["missing_entry"],
                    invalid_entry_stop_or_target_geometry=cell["invalid"],
                    entered_positions=cell["entered"],
                    observed_outcomes=len(observed),
                    censored_entered_outcomes=cell["censored"],
                    observed_only_cost_scenarios=cost_cases)
            for kind, expected in (
                ("confirmed", confirmed[name]), ("entered", entered[name]),
                ("missing_entry", entry_unobservable[name]),
                ("invalid", invalid_entry_geometry[name]),
                ("censored", censored[name])):
                if sum(cell[kind] for cell in displacement[name].values()) != expected:
                    raise RuntimeError("Displacement population reconciliation failed")
            if sum(len(cell["observed"]) for cell in displacement[name].values()) != len(trades):
                raise RuntimeError("Displacement observed population mismatch")
            # Each confirmed signal belongs to exactly one causal joint state.
            confluence_report = {}
            for key, cell in confluence[name].items():
                observed = cell["observed"]
                if cell["confirmed"] != (cell["missing_entry"] + cell["invalid"] +
                                         cell["entered"]):
                    raise RuntimeError("Confluence signal census mismatch")
                if cell["entered"] != cell["censored"] + len(observed):
                    raise RuntimeError("Confluence entered census mismatch")
                joint_costs = []
                for bps in (0, 5, 10, 20):
                    total = sum((r - abs(entry) * Q(bps) / Q(10000) / risk
                                 for r, entry, risk in observed), Q(0))
                    joint_costs.append(dict(
                        additional_round_trip_bps=bps,
                        observed_outcomes=len(observed),
                        mean_net_r=str(total / len(observed)) if observed else None))
                confluence_report[key] = dict(
                    confirmed_signals=cell["confirmed"],
                    confirmed_signals_without_observable_entry=cell["missing_entry"],
                    invalid_entry_stop_or_target_geometry=cell["invalid"],
                    entered_positions=cell["entered"],
                    observed_outcomes=len(observed),
                    censored_entered_outcomes=cell["censored"],
                    observed_only_cost_scenarios=joint_costs)
            for kind, expected in (
                ("confirmed", confirmed[name]), ("entered", entered[name]),
                ("missing_entry", entry_unobservable[name]),
                ("invalid", invalid_entry_geometry[name]),
                ("censored", censored[name])):
                if sum(cell[kind] for cell in confluence[name].values()) != expected:
                    raise RuntimeError("Confluence population reconciliation failed")
            if sum(len(cell["observed"]) for cell in confluence[name].values()) != len(trades):
                raise RuntimeError("Confluence observed population mismatch")
            reports[name] = dict(
                confirmation_fvg_mss_displacement_joint_census=dict(
                    states=confluence_report,
                    definition="FVG_THREE_CANDLE_AND_PRIOR_RANGE_BREAK_AND_BODY_DISPLACEMENT",
                    interpretation="EIGHT_WAY_CAUSAL_DESCRIPTIVE_CROSS_TAB_NOT_FILTER_OR_EDGE"),
                confirmation_body_displacement_census=dict(
                    definition="DIRECTIONAL_CONFIRMATION_BODY_GTE_PRIOR_MEDIAN_FULL_RANGE",
                    range_lookback_completed_bars=lookback,
                    threshold_equality_included=True,
                    states=displacement_report,
                    interpretation="CAUSAL_BODY_DISPLACEMENT_PROXY_NOT_ICT_VALIDATION_OR_ENTRY_FILTER_OR_EDGE"),
                confirmation_prior_range_break_census=dict(
                    definition="LONG_CLOSE_GT_PRIOR_LOOKBACK_HIGH_OR_SHORT_CLOSE_LT_PRIOR_LOOKBACK_LOW",
                    range_lookback_completed_bars=lookback,
                    states=structure_report,
                    interpretation="CAUSAL_MINIMAL_MSS_PROXY_NOT_PIVOT_MSS_OR_ENTRY_FILTER_OR_EDGE"),
                confirmation_three_candle_fvg_census=dict(
                    definition="PRIOR_HIGH_LT_CONFIRMATION_LOW_LONG_OR_PRIOR_LOW_GT_CONFIRMATION_HIGH_SHORT",
                    first_candle="LAST_COMPLETED_PRE_SWEEP",
                    middle_candle="COMPLETED_SWEEP",
                    third_candle="COMPLETED_CONFIRMATION",
                    states=fvg_report,
                    interpretation="CAUSAL_DESCRIPTIVE_FVG_ATTRITION_NOT_ENTRY_FILTER_OR_EDGE"),
                confirmed_signal_direction_census=dict(
                    directions=direction_report,
                    interpretation="CAUSAL_DIRECTIONAL_ATTRITION_OBSERVED_ONLY_NOT_EDGE"),
                pre_signal_volatility_regime_census=dict(
                    metric="MEDIAN_PRIOR_BAR_HIGH_LOW_RANGE_BPS_OF_CLOSE",
                    fixed_thresholds_bps=[10, 30],
                    lookback_completed_bars=lookback,
                    regimes=regime_report,
                    interpretation="CAUSAL_DESCRIPTIVE_OBSERVED_ONLY_NOT_SELECTION_OR_EDGE"),
                confirmed_signals=confirmed[name],
                entered_positions=entered[name],
                invalid_entry_stop_or_target_geometry=invalid_entry_geometry[name],
                observed_outcomes=len(trades),
                unresolved_or_unadmitted_signals=(confirmed[name] - len(trades)),
                all_confirmed_signals_resolved=(confirmed[name] > 0 and
                                                confirmed[name] == len(trades)),
                return_population_scope="OBSERVED_ENTERED_OUTCOMES_ONLY",
                censored_due_to_gaps_or_boundaries=censored[name],
                confirmed_signals_without_observable_entry=entry_unobservable[name],
                uncensored_mean_gross_r=(str(mean_gross_r) if trades else None),
                mean_r_cost_per_additional_bps=(str(cost_slope) if trades else None),
                positive_mean_break_even_additional_bps=(
                    str(break_even_bps) if break_even_bps is not None else None),
                cost_scenarios=cases,
                same_bar_stop_target_collision_census=dict(
                    collisions,
                    both_barriers_touched=sum(collisions.values()),
                    observed_outcomes_total=len(trades),
                    # On a *fixed admitted* population, only the source
                    # opens not already beyond stop could hypothetically
                    # replace a -1R stop with a +2R target. This is NOT a
                    # replay: alternate exits would change later admissions.
                    fixed_cohort_target_first_uplift_r_sum=str(
                        Q(3) * (collisions["opens_at_or_beyond_target"] +
                                collisions["opens_between_barriers_order_unknown"])),
                    fixed_cohort_target_first_uplift_r_per_observed=(
                        str(Q(3) * (collisions["opens_at_or_beyond_target"] +
                                    collisions["opens_between_barriers_order_unknown"])
                            / len(trades)) if trades else None),
                    interpretation="SOURCE_OHLC_FIXED_COHORT_SENSITIVITY_NOT_BACKTEST"),
                observed_exit_path_census=dict(
                    exit_path_counts[name],
                    observed_outcomes_total=len(trades),
                    adverse_source_open_extra_loss_r_sum=str(sum(
                        adverse_open_extra_loss_r[name], Q(0))),
                    adverse_source_open_extra_loss_r_max=(
                        str(max(adverse_open_extra_loss_r[name]))
                        if adverse_open_extra_loss_r[name] else None),
                    interpretation="SOURCE_OHLC_PROXY_NOT_EXECUTABLE_FILLS"),
                censored_entered_loss_stress_scenarios=censored_loss_stress,
                observed_holding_duration_census=dict(
                    observed_outcomes_total=len(trades),
                    observed_holding_15m_bars_sum=sum(observed_holding_bars[name]),
                    observed_holding_15m_bars_min=(min(observed_holding_bars[name])
                                                    if trades else None),
                    observed_holding_15m_bars_max=(max(observed_holding_bars[name])
                                                    if trades else None),
                    observed_holding_15m_bars_mean=(
                        str(Q(sum(observed_holding_bars[name])) / len(trades))
                        if trades else None),
                    censored_entered_positions=censored[name],
                    censored_observed_prefix_15m_bars_sum=sum(
                        censored_observed_prefix_bars[name]),
                    censored_observed_prefix_15m_bars_max=(
                        max(censored_observed_prefix_bars[name])
                        if censored[name] else None),
                    interpretation="SOURCE_CONTIGUOUS_BARS_NOT_BROKER_HOLDING_RECEIPTS"),
                illustrative_observed_time_cost_scenarios=time_cost_scenarios)
    return dict(protocol="source-local-sweep-confirmation-v3",
                source_authenticated=False, timezone_verified=False,
                untouched_holdout_verified=False, executable_broker_costs=False,
                verified_profitability=False, may_execute_order=False,
                split_index=split, bars=len(bars), lookback_15m=lookback,
                max_holding_15m=horizon, embargo_15m=embargo, cohorts=reports)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", help="Private HistData ASCII M1 ZIPs")
    args = parser.parse_args(argv)
    for name in args.archives:
        bars, quality = read_archive(name)
        print(json.dumps(dict(archive=Path(name).name, quality=quality,
                              research=research(bars)), sort_keys=True))


if __name__ == "__main__":
    main()
