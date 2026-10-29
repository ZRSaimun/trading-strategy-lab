"""Read-only, exploratory fixed-rule M1 confluence and cost-sensitivity census.

Source-wall-clock timestamps and single-side candles are NOT executable quotes.
No historical source authentication, trading permission, or profitability proof.
"""
from __future__ import annotations

import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile

POLICY = "exploratory-sweep20-mss3-fvg2-window5-nextopen-15m-v1"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
MAX_BARS = 500_000
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")


def _minute(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"\d{8} \d{6}", value):
        raise ValueError("Expected HistData source-wall YYYYMMDD HHMMSS")
    dt = datetime.strptime(value, "%Y%m%d %H%M%S")
    if dt.second:
        raise ValueError("Only completed M1 wall minutes accepted")
    return dt.toordinal() * 1440 + dt.hour * 60 + dt.minute


def _prices(row):
    if len(row) != 6:
        raise ValueError("Expected six HistData ASCII M1 columns")
    values = []
    for token in row[1:]:
        if not re.fullmatch(r"\d{1,20}(?:\.\d{1,12})?", token):
            raise ValueError("Noncanonical bounded positive decimal token")
        value = float(token)
        if not math.isfinite(value) or value < 0:
            raise ValueError("Nonfinite or negative value")
        values.append(value)
    o, h, l, c, volume = values
    if min(o, h, l, c) <= 0 or l > min(o, c) or h < max(o, c):
        raise ValueError("Invalid OHLC envelope")
    return o, h, l, c


def _summarize(rows, costs):
    if not rows:
        return {"count": 0, "mean_gross_bps": None,
                "mean_net_bps_by_roundtrip_cost": {str(x): None for x in costs},
                "gross_win_fraction": None}
    gross = sum(rows) / len(rows)
    return {
        "count": len(rows), "mean_gross_bps": round(gross, 6),
        "mean_net_bps_by_roundtrip_cost": {
            str(x): round(gross - x, 6) for x in costs
        },
        "gross_win_fraction": round(sum(x > 0 for x in rows) / len(rows), 6),
    }


def audit_m1_cost_sensitivity(bars, *, instrument, provider, archive_sha256,
                              horizon_minutes=15, roundtrip_cost_bps=(0, 5, 10, 20)):
    """Frozen rule: 20-bar sweep/reclaim; 3-bar MSS and wick FVG in next 5 bars.

    Entry is the *next* contiguous candle open, exit is the 15th contiguous
    candle close (including entry candle). Gaps censor outcomes, and a new
    entry cannot overlap the prior selected horizon. All results are purely
    exploratory, without BID/ASK, fill, financing or verified UTC clocks.
    """
    if any(not isinstance(x, str) or not _ID.fullmatch(x)
           for x in (instrument, provider)):
        raise ValueError("Invalid source identity")
    if not isinstance(archive_sha256, str) or not _SHA.fullmatch(archive_sha256):
        raise ValueError("SHA-256 archive identity required")
    if type(horizon_minutes) is not int or not 1 <= horizon_minutes <= 1440:
        raise ValueError("Invalid fixed horizon")
    costs = roundtrip_cost_bps
    if (not isinstance(costs, (list, tuple)) or not 1 <= len(costs) <= 8
            or any(type(x) is not int or not 0 <= x <= 100 for x in costs)
            or list(costs) != sorted(set(costs))):
        raise ValueError("Costs must be sorted distinct integer bps 0..100")
    if not isinstance(bars, list) or not 1 <= len(bars) <= MAX_BARS:
        raise ValueError("Bounded nonempty archive bars required")
    t, o, h, l, c = [], [], [], [], []
    digest = hashlib.sha256()
    for row in bars:
        if not isinstance(row, (tuple, list)) or len(row) != 6:
            raise ValueError("Expected raw six-field archive row")
        minute = _minute(row[0])
        op, hi, lo, cl = _prices(row)
        t.append(minute); o.append(op); h.append(hi); l.append(lo); c.append(cl)
        digest.update(json.dumps(row, separators=(",", ":"), ensure_ascii=True).encode())
        digest.update(b"\n")

    n = len(t)
    starts = [0] * n
    breaks = backward = duplicate = 0
    for i in range(1, n):
        if t[i] != t[i - 1] + 1:
            breaks += 1
            backward += t[i] < t[i - 1]
            duplicate += t[i] == t[i - 1]
            starts[i] = i
        else:
            starts[i] = starts[i - 1]
    active = []
    signals = []
    sweeps = ambiguous = 0
    for i in range(n):
        if starts[i] == i:
            active = []
        active = [(k, direction) for k, direction in active if i - k <= 5]
        confirmed = []
        if i - starts[i] >= 3:
            for k, direction in active:
                if direction == 1:
                    mss = c[i] > max(h[i - 3:i]) and c[i] > o[i]
                    fvg = i - starts[i] >= 2 and l[i] > h[i - 2]
                else:
                    mss = c[i] < min(l[i - 3:i]) and c[i] < o[i]
                    fvg = i - starts[i] >= 2 and h[i] < l[i - 2]
                if mss and fvg:
                    confirmed.append((k, direction))
        if len(confirmed) == 1:
            if i - starts[i] >= 14:
                signals.append((i, confirmed[0][1]))
            active.remove(confirmed[0])
        elif len(confirmed) > 1:
            ambiguous += 1
            for item in confirmed:
                active.remove(item)
        if i - starts[i] >= 20:
            floor = min(l[i - 20:i]); ceiling = max(h[i - 20:i])
            low_sweep = l[i] < floor
            high_sweep = h[i] > ceiling
            if low_sweep and high_sweep:
                ambiguous += 1
            elif low_sweep and floor < c[i] < ceiling:
                active.append((i, 1)); sweeps += 1
            elif high_sweep and floor < c[i] < ceiling:
                active.append((i, -1)); sweeps += 1
    gross = []
    last_exit = -1
    censored = overlapping = 0
    for i, direction in signals:
        entry = i + 1
        end = entry + horizon_minutes - 1
        if (end >= n or t[entry] != t[i] + 1
                or starts[end] > entry):
            censored += 1
            continue
        if entry <= last_exit:
            overlapping += 1
            continue
        gross.append(direction * (c[end] - o[entry]) / o[entry] * 10000)
        last_exit = end
    split = len(gross) * 7 // 10
    source = {"instrument": instrument, "provider": provider,
              "archive_sha256": archive_sha256,
              "price_side": "UNVERIFIED_SINGLE_SIDE",
              "time_convention": "SOURCE_WALL_UNVERIFIED"}
    body = {
        "policy": POLICY, "source": source, "bar_count": n,
        "bar_manifest_sha256": digest.hexdigest(),
        "timestamp_discontinuities": breaks, "backward_jumps": backward,
        "adjacent_duplicates": duplicate, "sweep_count": sweeps,
        "ambiguous_count": ambiguous, "confirmed_count": len(signals),
        "censored_gap_or_end": censored, "excluded_overlap": overlapping,
        "horizon_minutes": horizon_minutes, "roundtrip_cost_bps": list(costs),
        "development_exploratory": _summarize(gross[:split], costs),
        "later_exploratory_not_holdout": _summarize(gross[split:], costs),
        "all_exploratory": _summarize(gross, costs),
    }
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return {
        **body, "research_schema_version": 1,
        "research_sha256": hashlib.sha256(canonical.encode()).hexdigest(),
        "research_only": True, "trade_authorized": False,
        "verified_profitability": False, "protected_holdout": False,
        "source_authenticity_verified": False, "executable_quotes_verified": False,
        "financing_modeled": False, "market_calendar_verified": False,
        "warning": "Exploratory single-side M1 proxy, source-wall time; no executable spreads, slippage receipts, financing, protected holdout or authenticated provenance. Costs are illustrative flat round-trip bps, not verified broker charges.",
    }


def audit_histdata_ascii_zip(path, *, instrument, provider="HistData",
                             horizon_minutes=15, roundtrip_cost_bps=(0, 5, 10, 20)):
    """Read a bounded original ZIP without extraction, network or writes."""
    path = Path(path)
    if not path.is_file() or path.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError("Missing or oversized original archive")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    rows = []
    with zipfile.ZipFile(path) as archive:
        members = [x for x in archive.infolist() if x.filename.lower().endswith(".csv")]
        if len(members) != 1 or members[0].file_size > MAX_MEMBER_BYTES:
            raise ValueError("Exactly one bounded CSV member required")
        with archive.open(members[0]) as raw:
            with io.TextIOWrapper(raw, encoding="utf-8", errors="strict", newline="") as stream:
                for row in csv.reader(stream, delimiter=";"):
                    if len(rows) >= MAX_BARS:
                        raise ValueError("Archive row limit exceeded")
                    rows.append(row)
    # Re-hash the original compressed bytes to detect changes during replay.
    after = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            after.update(chunk)
    if after.digest() != digest.digest():
        raise ValueError("Archive changed during read-only research")
    return audit_m1_cost_sensitivity(
        rows, instrument=instrument, provider=provider,
        archive_sha256=digest.hexdigest(), horizon_minutes=horizon_minutes,
        roundtrip_cost_bps=roundtrip_cost_bps,
    )
