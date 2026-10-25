"""Offline, strictly pre-signal M1 volatility regime audit for frozen intents.

Fixed, non-optimized ATR-ratio strata. No future candle, trade outcome, broker
quote, order, market-data request, or database mutation is accepted.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, ROUND_HALF_EVEN, localcontext

from app.frozen_next_open_intent import fingerprint_next_open_intents

_PROTOCOL = "frozen-m1-volatility-evidence-v1"
_REPORT = "frozen-intent-asof-volatility-regime-v1"
_SOURCE = ("instrument", "provider", "venue", "archive_sha256", "price_side", "horizon_minutes")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DEC = re.compile(r"[+]?(?:\d{1,20})(?:\.\d{1,12})?\Z")
_MAX_CLOCK = 8640000000
_MINUTE = 60
_WINDOW = 30
_MAX_ROWS = 100000
_LOW = Decimal("0.75")
_HIGH = Decimal("1.50")
_QUANT = Decimal("0.000001")
_BAR = ("at", "open", "high", "low", "close")
_STATES = ("COMPRESSION", "NORMAL", "EXPANSION",
           "UNKNOWN_INCOMPLETE_CONTEXT", "UNKNOWN_ZERO_BASELINE")


def _exact(value, fields, name):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise ValueError(f"{name} must contain exactly the declared fields")


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_CLOCK and value % _MINUTE == 0


def _price(value):
    if not isinstance(value, str) or not _DEC.fullmatch(value):
        raise ValueError("Positive bounded decimal string required")
    result = Decimal(value)
    if result <= 0:
        raise ValueError("Nonpositive historical price")
    return result


def _validate_evidence(evidence):
    _exact(evidence, ("protocol", "source", "observations"), "Volatility evidence")
    if evidence["protocol"] != _PROTOCOL:
        raise ValueError("Unsupported volatility evidence protocol")
    source = evidence["source"]
    _exact(source, _SOURCE, "Evidence source")
    for key in ("instrument", "provider", "venue"):
        if not isinstance(source[key], str) or not 1 <= len(source[key].strip()) <= 128:
            raise ValueError("Invalid evidence source identity")
    if not isinstance(source["archive_sha256"], str) or not _SHA.fullmatch(source["archive_sha256"]):
        raise ValueError("Invalid archive SHA-256")
    if source["price_side"] not in ("BID", "ASK", "MID"):
        raise ValueError("Invalid evidence price side")
    if type(source["horizon_minutes"]) is not int or not 1 <= source["horizon_minutes"] <= 1440:
        raise ValueError("Invalid evidence horizon")
    rows = evidence["observations"]
    if not isinstance(rows, list) or not 1 <= len(rows) <= _MAX_ROWS:
        raise ValueError("Nonempty bounded evidence population required")
    ids = set()
    for row in rows:
        _exact(row, ("path_id", "bars"), "Observation")
        path_id = row["path_id"]
        if not isinstance(path_id, str) or not _ID.fullmatch(path_id) or path_id in ids:
            raise ValueError("Invalid or duplicate evidence path ID")
        ids.add(path_id)
        bars = row["bars"]
        if not isinstance(bars, list) or len(bars) > _WINDOW:
            raise ValueError("At most 30 M1 pre-signal candles permitted")
        previous = None
        for bar in bars:
            _exact(bar, _BAR, "M1 bar")
            at = bar["at"]
            if not _clock(at) or (previous is not None and at <= previous):
                raise ValueError("Invalid, duplicate or backward M1 timestamp")
            previous = at
            o, h, l, c = (_price(bar[key]) for key in ("open", "high", "low", "close"))
            if not l <= min(o, c) <= max(o, c) <= h:
                raise ValueError("Invalid M1 OHLC envelope")
    return rows


def fingerprint_pre_signal_volatility_evidence(evidence):
    """Order-independent consistency digest, not proof of pre-outcome registration."""
    rows = _validate_evidence(evidence)
    canonical = dict(protocol=_PROTOCOL, source=evidence["source"],
                     observations=sorted(rows, key=lambda row: row["path_id"]))
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _regime(bars, signal_at):
    # Signal at is the OPEN of the completed confirmation M1 candle. Its close
    # is signal_at+60. The final permissible bar opens exactly at signal_at.
    first = signal_at - (_WINDOW - 1) * _MINUTE
    for bar in bars:
        if not first <= bar["at"] <= signal_at:
            raise ValueError("Future or out-of-window M1 candle in pre-signal evidence")
    if len(bars) != _WINDOW or any(
        bar["at"] != first + i * _MINUTE for i, bar in enumerate(bars)
    ):
        return "UNKNOWN_INCOMPLETE_CONTEXT", None, None, None
    with localcontext() as ctx:
        ctx.prec = 50
        parsed = [
            tuple(_price(bar[k]) for k in ("open", "high", "low", "close"))
            for bar in bars
        ]
        ranges = []
        for i in range(1, _WINDOW):
            previous_close = parsed[i - 1][3]
            _, high, low, _ = parsed[i]
            ranges.append(max(high - low, abs(high - previous_close),
                              abs(low - previous_close)))
        # Disjoint 14-TR windows: indices 1..14 and 16..29. TR15 is unused.
        # All observations end at the completed signal candle, not next open.
        baseline = sum(ranges[:14], Decimal(0)) / Decimal(14)
        recent = sum(ranges[15:], Decimal(0)) / Decimal(14)
        if baseline <= 0:
            return "UNKNOWN_ZERO_BASELINE", None, None, None
        ratio = recent / baseline
        state = "COMPRESSION" if ratio <= _LOW else (
            "EXPANSION" if ratio >= _HIGH else "NORMAL")
        return (state,
                format(baseline.quantize(_QUANT, rounding=ROUND_HALF_EVEN), "f"),
                format(recent.quantize(_QUANT, rounding=ROUND_HALF_EVEN), "f"),
                format(ratio.quantize(_QUANT, rounding=ROUND_HALF_EVEN), "f"))


def audit_asof_volatility_regimes(manifest, expected_manifest_sha256, evidence,
                                 expected_evidence_sha256, *, sample_limit=20):
    """Classify every eligible frozen intent using only completed M1 history.

    Unknown contexts stay in the denominator and cannot be removed to improve
    performance. Labels are descriptive and never authorize a trading filter.
    """
    if type(sample_limit) is not int or not 0 <= sample_limit <= 50:
        raise ValueError("Invalid sample limit")
    if not isinstance(expected_manifest_sha256, str) or not _SHA.fullmatch(expected_manifest_sha256):
        raise ValueError("Expected manifest SHA-256 required")
    if not isinstance(expected_evidence_sha256, str) or not _SHA.fullmatch(expected_evidence_sha256):
        raise ValueError("Expected evidence SHA-256 required")
    digest = fingerprint_next_open_intents(manifest)
    if digest != expected_manifest_sha256:
        raise ValueError("Frozen intent fingerprint mismatch")
    evidence_digest = fingerprint_pre_signal_volatility_evidence(evidence)
    if evidence_digest != expected_evidence_sha256:
        raise ValueError("Volatility evidence fingerprint mismatch")
    if evidence["source"] != manifest["source"]:
        raise ValueError("Volatility evidence and intent source mismatch")
    expected = {row["path_id"]: row for row in manifest["eligible_intents"]}
    supplied = {row["path_id"]: row["bars"] for row in evidence["observations"]}
    if set(supplied) != set(expected):
        raise ValueError("Incomplete or unregistered frozen intent evidence population")
    counts = {state: 0 for state in _STATES}
    samples = []
    for intent in sorted(expected.values(), key=lambda x: (x["signal_at"], x["path_id"])):
        state, baseline, recent, ratio = _regime(supplied[intent["path_id"]],
                                                  intent["signal_at"])
        counts[state] += 1
        if len(samples) < sample_limit:
            samples.append(dict(path_id=intent["path_id"], signal_at=intent["signal_at"],
                                regime=state, baseline_atr14=baseline,
                                recent_atr14=recent, recent_to_baseline_ratio=ratio))
    unknown = counts["UNKNOWN_INCOMPLETE_CONTEXT"] + counts["UNKNOWN_ZERO_BASELINE"]
    return dict(
        protocol=_REPORT, manifest_sha256=digest, evidence_sha256=evidence_digest,
        status="INCOMPLETE_PRE_SIGNAL_CONTEXT" if unknown else "DESCRIPTIVE_REGIMES_ONLY",
        eligible_intents=len(expected),
        declared_pre_signal_exclusions=len(manifest["excluded_signals"]),
        counts=counts, unknown_regimes=unknown,
        fixed_compression_ratio_lte="0.75", fixed_expansion_ratio_gte="1.50",
        baseline_true_range_indices="1..14", recent_true_range_indices="16..29",
        sample_limit=sample_limit, intent_samples=samples,
        complete_against_supplied_manifest=True, all_eligible_intents_retained=True,
        no_post_signal_candle_used=True, source_authenticated=False,
        source_rights_verified=False, independent_preregistration_verified=False,
        untouched_holdout_verified=False, executable_spreads_verified=False,
        may_exclude_signals=False, may_execute_order=False,
        verified_profitability=False,
        warning=("Pre-signal volatility labels are fixed descriptive hypotheses, "
                 "not trading signals, post-hoc filters, authenticated source data, "
                 "or evidence of a profitable edge. Self-supplied digests do not "
                 "prove pre-outcome registration. Preserve unknown contexts and "
                 "evaluate any preregistered stratification only on untouched "
                 "chronological holdouts with realistic executable costs."),
    )
