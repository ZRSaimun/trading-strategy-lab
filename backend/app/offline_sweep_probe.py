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
    # A confirmed signal must not vanish from the sample simply because its
    # *future* entry bar is missing, crosses a source gap, or enters embargo.
    # These have no observable fill and must not be counted as entered trades.
    entry_unobservable = {"development": 0, "exploratory_later": 0}
    next_free = 0
    for i in range(lookback, len(bars) - 1):
        cohort = ("development" if i < split - embargo else
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
        entry_index = i + 2
        if (entry_index >= len(bars) or
                bars[entry_index].segment != confirmation.segment or
                bars[entry_index].time - confirmation.time != BAR_STEP or
                (cohort == "development" and entry_index >= split - embargo) or
                (cohort == "exploratory_later" and entry_index < split + embargo)):
            entry_unobservable[cohort] += 1
            # No entry observation means no demonstrated position exposure.
            # Do not manufacture a fill, return or position reservation.
            continue
        entry = bars[entry_index].o
        stop = sweep.l if is_long else sweep.h
        risk = entry - stop if is_long else stop - entry
        if risk <= 0:
            continue
        target = entry + 2*risk if is_long else entry - 2*risk
        if target <= 0:
            continue
        outcome = None
        last = min(entry_index + horizon, len(bars))
        for j in range(entry_index, last):
            b = bars[j]
            if (b.segment != bars[entry_index].segment or
                    (j > entry_index and b.time - bars[j-1].time != BAR_STEP) or
                    (j >= split - embargo and cohort == "development") or
                    (j < split + embargo and cohort == "exploratory_later")):
                break
            stopped = b.l <= stop if is_long else b.h >= stop
            won = b.h >= target if is_long else b.l <= target
            if stopped:
                # A source OHLC bar can open beyond the stop while remaining
                # timestamp-contiguous. Crediting an exact -1R stop in that
                # case would erase observed adverse gap risk. Use the worse
                # source open as a *hypothetical proxy*, not an executable fill
                # or a bound on broker slippage. Stop still wins same-bar ties.
                adverse_open = (b.o < stop if is_long else b.o > stop)
                exit_proxy = b.o if adverse_open else stop
                outcome = ((exit_proxy-entry)/risk if is_long
                           else (entry-exit_proxy)/risk)
                next_free = j + 1
                break
            if won:
                outcome = Q(2)
                next_free = j + 1
                break
        else:
            if last - entry_index == horizon:
                last_close = bars[last-1].c
                outcome = (last_close-entry)/risk if is_long else (entry-last_close)/risk
                next_free = last
        if outcome is None:
            censored[cohort] += 1
            # A censored position has no observed exit. Do not admit another
            # hypothetical position inside its entire reserved holding window.
            # This is an analysis-only exclusion, not proof of a flat account.
            next_free = max(next_free, entry_index + horizon)
        else:
            cohorts[cohort].append((outcome, entry, risk))
    reports = {}
    with localcontext() as ctx:
        ctx.prec = 60
        for name, trades in cohorts.items():
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
            cases = []
            for bps in (0, 5, 10, 20):
                net = [r - abs(entry)*Q(bps)/Q(10000)/risk for r, entry, risk in trades]
                cases.append(dict(additional_round_trip_bps=bps, count=len(net),
                                  mean_net_r=str(sum(net, Q(0))/len(net)) if net else None,
                                  sum_net_r=str(sum(net, Q(0))),
                                  strictly_positive=sum(v > 0 for v in net)))
            reports[name] = dict(
                censored_due_to_gaps_or_boundaries=censored[name],
                confirmed_signals_without_observable_entry=entry_unobservable[name],
                uncensored_mean_gross_r=(str(mean_gross_r) if trades else None),
                mean_r_cost_per_additional_bps=(str(cost_slope) if trades else None),
                positive_mean_break_even_additional_bps=(
                    str(break_even_bps) if break_even_bps is not None else None),
                cost_scenarios=cases)
    return dict(protocol="source-local-sweep-confirmation-v2",
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
