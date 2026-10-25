"""Deterministic completed-M1 sweep -> MSS-proxy + FVG *research* detector.

No trading decisions, backtest outcomes, broker execution or data writes. A
self-declared snapshot is not authenticated market data or preregistration.
"""
import hashlib
import json
import re
from decimal import Decimal

_POLICY = "causal-m1-sweep20-mss3-fvg2-window5-v1"
_HYPOTHESIS = "CRT_ICT_SWEEP_MSS_FVG_CANDIDATE"
_SOURCE_FIELDS = frozenset(("instrument", "provider", "venue", "archive_sha256", "price_side", "horizon_minutes"))
_BAR_FIELDS = frozenset(("at", "open", "high", "low", "close"))
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DEC = re.compile(r"[+]?(?:\d{1,20})(?:\.\d{1,12})?\Z")
_MINUTE = 60
_MAX_CLOCK = 8640000000
_MAX_BARS = 250000
_LOOKBACK = 20
_MSS_LOOKBACK = 3
_CONFIRM_WINDOW = 5


def _minute(value):
    return type(value) is int and 60 <= value <= _MAX_CLOCK and value % _MINUTE == 0


def _price(value):
    if not isinstance(value, str) or not _DEC.fullmatch(value):
        raise ValueError("OHLC requires bounded positive decimal strings")
    result = Decimal(value)
    if result <= 0:
        raise ValueError("OHLC requires positive prices")
    return result


def _validate_source(source):
    if not isinstance(source, dict) or set(source) != _SOURCE_FIELDS:
        raise ValueError("Exact frozen-next-open source identity required")
    for key in ("instrument", "provider", "venue"):
        if not isinstance(source[key], str) or not _ID.fullmatch(source[key]):
            raise ValueError("Invalid source identity")
    if not isinstance(source["archive_sha256"], str) or not _SHA.fullmatch(source["archive_sha256"]):
        raise ValueError("Invalid archive digest")
    if source["price_side"] not in ("BID", "ASK", "MID"):
        raise ValueError("Unknown price side")
    if type(source["horizon_minutes"]) is not int or not 1 <= source["horizon_minutes"] <= 1440:
        raise ValueError("Invalid frozen horizon")


def _validate_bars(bars, cutoff):
    if not isinstance(bars, list) or not 1 <= len(bars) <= _MAX_BARS:
        raise ValueError("Nonempty bounded completed M1 snapshot required")
    if not _minute(cutoff):
        raise ValueError("Invalid observed-through UTC close")
    parsed = []
    previous = None
    for row in bars:
        if not isinstance(row, dict) or set(row) != _BAR_FIELDS:
            raise ValueError("M1 bar has unknown or missing fields")
        at = row["at"]
        if not _minute(at) or at + 60 > cutoff or (previous is not None and at <= previous):
            raise ValueError("Noncompleted, nonminute, duplicate or backward M1 timestamp")
        previous = at
        o, h, l, c = (_price(row[key]) for key in ("open", "high", "low", "close"))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid historical OHLC envelope")
        parsed.append((at, o, h, l, c))
    if parsed[-1][0] + 60 != cutoff:
        raise ValueError("Last completed candle must close at declared snapshot cutoff")
    return parsed


def _event_id(source, sweep_at, confirm_at, direction):
    identity = json.dumps([source, sweep_at, confirm_at, direction], sort_keys=True, separators=(",", ":"))
    return "m1cf-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]


def detect_completed_m1_confluence(source, bars, observed_through_close_at):
    """Scan completed candles only; emit bridge-compatible *hypothesis* candidates.

    Fixed, deliberately strict rule (not an optimized trading system):
    sweep prior 20-bar high/low, reclaim; within next 5 completed M1 bars,
    same-direction close breaks previous 3-bar structure AND forms 3-candle
    wick FVG. A gap resets all warmups; unfinished sweeps remain pending.
    """
    _validate_source(source)
    data = _validate_bars(bars, observed_through_close_at)
    candidates = []
    active = []
    segment_start = 0
    sweep_count = expired_count = pending_count = gap_censored_count = 0
    ambiguous_sweep_count = 0
    seen_confirmation = set()
    for i, bar in enumerate(data):
        at, o, h, l, c = bar
        if i and at != data[i - 1][0] + _MINUTE:
            gap_censored_count += len(active)
            active = []
            segment_start = i
        active_kept = []
        for sweep_index, direction in active:
            if i - sweep_index > _CONFIRM_WINDOW:
                expired_count += 1
            else:
                active_kept.append((sweep_index, direction))
        active = active_kept
        confirming = []
        for sweep_index, direction in active:
            if i - segment_start < _MSS_LOOKBACK or i - sweep_index < 1:
                continue
            prior = data[i - _MSS_LOOKBACK:i]
            if direction == "LONG":
                mss = c > max(x[2] for x in prior) and c > o
                fvg = i - segment_start >= 2 and l > data[i - 2][2]
            else:
                mss = c < min(x[3] for x in prior) and c < o
                fvg = i - segment_start >= 2 and h < data[i - 2][3]
            if mss and fvg:
                confirming.append((sweep_index, direction))
        if len(confirming) > 1:
            raise ValueError("Competing sweep hypotheses at one confirmation close; do not cherry-pick")
        if confirming:
            sweep_index, direction = confirming[0]
            close_at = at + _MINUTE
            if close_at in seen_confirmation:
                raise ValueError("Duplicate confirmation close")
            seen_confirmation.add(close_at)
            if i - segment_start < 14:
                raise ValueError("Missing contiguous pre-signal ATR warmup")
            candidate = dict(
                path_id=_event_id(source, data[sweep_index][0], close_at, direction),
                confirmation_close_at=close_at,
                direction=direction,
                hypothesis=_HYPOTHESIS,
                m1_pre_signal=[dict(bars[k]) for k in range(i - 14, i + 1)],
            )
            candidates.append(candidate)
            active.remove(confirming[0])
        if i - segment_start >= _LOOKBACK:
            preceding = data[i - _LOOKBACK:i]
            floor = min(x[3] for x in preceding)
            ceiling = max(x[2] for x in preceding)
            low_sweep = l < floor
            high_sweep = h > ceiling
            if low_sweep and high_sweep:
                ambiguous_sweep_count += 1
            elif low_sweep and floor < c < ceiling:
                active.append((i, "LONG"))
                sweep_count += 1
            elif high_sweep and floor < c < ceiling:
                active.append((i, "SHORT"))
                sweep_count += 1
    for sweep_index, _direction in active:
        if len(data) - 1 - sweep_index >= _CONFIRM_WINDOW:
            expired_count += 1
        else:
            pending_count += 1
    canonical = dict(policy=_POLICY, source=source, observed_through_close_at=observed_through_close_at,
                     bars=bars)
    digest = hashlib.sha256(json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                                       ensure_ascii=True, allow_nan=False).encode("utf-8")).hexdigest()
    return dict(
        policy=_POLICY, source=dict(source), observed_through_close_at=observed_through_close_at,
        snapshot_sha256=digest, candidates=candidates, sweep_count=sweep_count,
        confirmed_count=len(candidates), expired_sweeps=expired_count,
        pending_sweeps=pending_count, gap_censored_sweeps=gap_censored_count,
        ambiguous_double_sweeps=ambiguous_sweep_count,
        source_authenticated=False, independently_preregistered=False,
        untouched_holdout_verified=False, executable_quotes_verified=False,
        verified_profitability=False,
        warning="Strict M1 sweep/MSS-proxy/FVG hypotheses only. Self-supplied snapshot hash does not prove authenticity, licensing, population completeness, prior registration, broker fills or profitable returns.",
    )
