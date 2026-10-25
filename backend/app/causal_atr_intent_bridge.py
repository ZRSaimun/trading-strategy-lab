"""Causal, fixed-policy M1 ATR bracket compiler for offline CRT/ICT candidates.

Consumes already-identified confirmation clocks, never invents confirmations or
reads an M1 candle at/after confirmation close. No broker orders or data writes.
"""
import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from app.frozen_next_open_intent import fingerprint_next_open_intents

_POLICY = "completed-m1-atr14-stop1p5-target3-v1"
_HYPOTHESIS = "CRT_ICT_SWEEP_MSS_FVG_CANDIDATE"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_DEC = re.compile(r"[+]?(?:\d{1,20})(?:\.\d{1,12})?\Z")
_QUANT = Decimal("0.000000000001")
_MINUTE = 60
_MAX_SIGNALS = 10000
_MAX_CLOCK = 8640000000
_BAR_FIELDS = ("at", "open", "high", "low", "close")
_SIGNAL_FIELDS = ("path_id", "confirmation_close_at", "direction", "hypothesis", "m1_pre_signal")


def _exact(row, fields, name):
    if not isinstance(row, dict) or set(row) != set(fields):
        raise ValueError(f"{name} must contain exactly the declared fields")


def _price(value):
    if not isinstance(value, str) or not _DEC.fullmatch(value):
        raise ValueError("Positive bounded decimal string required")
    price = Decimal(value)
    if price <= 0:
        raise ValueError("Nonpositive historical price")
    return price


def _utc_minute(value):
    return type(value) is int and _MINUTE <= value <= _MAX_CLOCK and value % _MINUTE == 0


def _candidate(signal):
    _exact(signal, _SIGNAL_FIELDS, "Candidate")
    path_id = signal["path_id"]
    close_at = signal["confirmation_close_at"]
    if not isinstance(path_id, str) or not _ID.fullmatch(path_id):
        raise ValueError("Invalid candidate ID")
    if not _utc_minute(close_at):
        raise ValueError("Invalid completed confirmation UTC close")
    if signal["direction"] not in ("LONG", "SHORT"):
        raise ValueError("Invalid candidate direction")
    if signal["hypothesis"] != _HYPOTHESIS:
        raise ValueError("Unsupported unverified upstream hypothesis")
    bars = signal["m1_pre_signal"]
    if not isinstance(bars, list) or len(bars) > 15:
        raise ValueError("At most fifteen preceding M1 bars allowed")
    parsed = []
    previous = None
    for row in bars:
        _exact(row, _BAR_FIELDS, "M1 bar")
        at = row["at"]
        if not _utc_minute(at) or at >= close_at:
            raise ValueError("Nonminute, future or not-yet-completed M1 bar")
        if previous is not None and at <= previous:
            raise ValueError("Duplicate or backward pre-signal M1 timestamp")
        previous = at
        o, h, l, c = (_price(row[key]) for key in ("open", "high", "low", "close"))
        if not l <= min(o, c) <= max(o, c) <= h:
            raise ValueError("Invalid pre-signal M1 OHLC envelope")
        parsed.append((at, o, h, l, c))
    return parsed


def _bracket(parsed, close_at, direction):
    # 15 strictly contiguous COMPLETED bars supply 14 true ranges, including
    # the previous close. A missing minute cannot be interpolated or ignored.
    expected_start = close_at - 15 * _MINUTE
    if len(parsed) != 15 or any(
        row[0] != expected_start + i * _MINUTE for i, row in enumerate(parsed)
    ):
        return None, "PRE_SIGNAL_DATA_GAP"
    with localcontext() as ctx:
        ctx.prec = 50
        ranges = []
        for i in range(1, 15):
            _, _, high, low, _ = parsed[i]
            previous_close = parsed[i - 1][4]
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        atr = sum(ranges, Decimal(0)) / Decimal(14)
        anchor = parsed[-1][4]
        if atr <= 0:
            return None, "INVALID_PRE_SIGNAL_CONTEXT"
        sign = Decimal(1) if direction == "LONG" else Decimal(-1)
        stop = (anchor - sign * Decimal("1.5") * atr).quantize(_QUANT, rounding=ROUND_HALF_EVEN)
        target = (anchor + sign * Decimal("3") * atr).quantize(_QUANT, rounding=ROUND_HALF_EVEN)
        if (stop <= 0 or target <= 0 or
            not (stop < anchor < target if direction == "LONG" else target < anchor < stop)):
            return None, "INVALID_PRE_SIGNAL_CONTEXT"
        stop_text, target_text = format(stop, "f"), format(target, "f")
        if not _DEC.fullmatch(stop_text) or not _DEC.fullmatch(target_text):
            return None, "INVALID_PRE_SIGNAL_CONTEXT"
        return (stop_text, target_text), None


def compile_causal_atr_intents(source, candidates):
    """Freeze a complete candidate population before the unknown next M1 open.

    The output manifest can be passed to audit_next_open_intents. Candidate
    detection, source authenticity, rights, preregistration and fills are NOT
    verified. Any pre-signal gap/invalid ATR becomes a declared exclusion,
    which causes the downstream population mean to be withheld.
    """
    if not isinstance(source, dict):
        raise ValueError("Source identity object required")
    if not isinstance(candidates, list) or not 1 <= len(candidates) <= _MAX_SIGNALS:
        raise ValueError("Nonempty bounded candidate population required")
    seen_ids, seen_closes = set(), set()
    eligible, excluded = [], []
    for candidate in candidates:
        parsed = _candidate(candidate)
        path_id, close_at = candidate["path_id"], candidate["confirmation_close_at"]
        if path_id in seen_ids or close_at in seen_closes:
            raise ValueError("Duplicate candidate ID or confirmation close")
        seen_ids.add(path_id)
        seen_closes.add(close_at)
        bracket, reason = _bracket(parsed, close_at, candidate["direction"])
        common = dict(path_id=path_id, signal_at=close_at - _MINUTE)
        if reason:
            excluded.append(dict(**common, reason=reason))
        else:
            stop, target = bracket
            eligible.append(dict(**common, direction=candidate["direction"],
                                 stop=stop, target=target))
    if not eligible:
        raise ValueError("No eligible intents; do not silently publish an empty backtest")
    manifest = dict(protocol="frozen-next-open-intent-v1", source=dict(source),
                    eligible_intents=eligible, excluded_signals=excluded)
    digest = fingerprint_next_open_intents(manifest)  # Existing strict schema validation.
    canonical = dict(policy=_POLICY, source=source, manifest=manifest,
                     candidates=sorted(candidates, key=lambda c: (c["confirmation_close_at"], c["path_id"])))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    evidence_sha = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return dict(policy=_POLICY, manifest=manifest, manifest_sha256=digest,
                pre_signal_evidence_sha256=evidence_sha,
                candidate_count=len(candidates), eligible_count=len(eligible),
                excluded_count=len(excluded),
                status="PRE_SIGNAL_EXCLUSIONS" if excluded else "FROZEN_CANDIDATES_UNVERIFIED",
                upstream_signal_verified=False, source_rights_and_utc_verified=False,
                independently_preregistered=False, untouched_holdout_verified=False,
                broker_fills_verified=False, verified_profitability=False,
                warning="ATR policy is an unoptimized research convention, not a validated CRT/ICT signal or executable stop. Preserve independently timestamped hashes before outcome data; source rights, full candidate population, holdout and broker costs remain unverified.")
