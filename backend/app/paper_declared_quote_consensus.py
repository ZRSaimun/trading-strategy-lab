"""Read-only, caller-declared cross-feed quote sanity review.

No broker authentication, trade authorization, risk reservation or network I/O.
Two matching caller-declared feeds are NOT independent evidence of market truth.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import re
from typing import Any

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,79}\Z")
_DEC = re.compile(r"(?:0|[1-9][0-9]{0,15})(?:\.[0-9]{1,8})?\Z")
_MAX_MS = 8_640_000_000_000_000
_QUOTE = {"source", "instrument", "bid", "ask", "observed_at_ms", "received_at_ms"}
_LIMITS = {"max_quote_age_ms", "max_transport_lag_ms", "max_inter_source_skew_ms", "max_mid_divergence_bps", "max_spread_bps"}


def _object(value: Any, fields: set[str], name: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"Invalid {name} fields")
    return value


def _id(value: Any, name: str) -> str:
    if type(value) is not str or not _ID.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    return value


def _decimal(value: Any, name: str) -> Decimal:
    if type(value) is not str or not _DEC.fullmatch(value):
        raise ValueError(f"Invalid {name}")
    result = Decimal(value)
    if result <= 0:
        raise ValueError(f"Invalid {name}")
    return result


def _ms(value: Any, name: str) -> int:
    if type(value) is not int or not 0 <= value <= _MAX_MS:
        raise ValueError(f"Invalid {name}")
    return value


def inspect_declared_quote_consensus(instrument: str, primary_source: str,
                                     quotes: list[dict], limits: dict,
                                     now_ms: int) -> dict[str, Any]:
    """Check declared bid/ask consensus; never return an order permission.

    All feeds and their timestamps are untrusted, caller-declared evidence.
    Invalid schemas fail closed with ValueError. Disagreement produces HOLD.
    """
    instrument = _id(instrument, "instrument")
    primary_source = _id(primary_source, "primary source")
    now = _ms(now_ms, "check time")
    p = _object(limits, _LIMITS, "quote policy")
    for key in ("max_quote_age_ms", "max_transport_lag_ms", "max_inter_source_skew_ms"):
        if type(p[key]) is not int or not 1 <= p[key] <= 60_000:
            raise ValueError(f"Invalid {key}")
    divergence = _decimal(p["max_mid_divergence_bps"], "max_mid_divergence_bps")
    spread = _decimal(p["max_spread_bps"], "max_spread_bps")
    if divergence > 10_000 or spread > 10_000:
        raise ValueError("Unsafe quote policy")
    if type(quotes) is not list or not 2 <= len(quotes) <= 5:
        raise ValueError("Expected 2 to 5 quote sources")
    failures: set[str] = set()
    seen: set[str] = set()
    observations: list[int] = []
    mids: list[Decimal] = []
    rows: list[tuple[Decimal, Decimal]] = []
    primary_seen = False
    with localcontext() as ctx:
        ctx.prec = 80
        for raw in quotes:
            q = _object(raw, _QUOTE, "quote")
            source = _id(q["source"], "quote source")
            quoted_instrument = _id(q["instrument"], "quote instrument")
            bid = _decimal(q["bid"], "bid")
            ask = _decimal(q["ask"], "ask")
            observed = _ms(q["observed_at_ms"], "observation time")
            received = _ms(q["received_at_ms"], "receipt time")
            if source in seen:
                failures.add("duplicate_quote_source")
            seen.add(source)
            primary_seen |= source == primary_source
            if quoted_instrument != instrument:
                failures.add("instrument_mismatch")
            if ask <= bid:
                failures.add("crossed_or_locked_quote")
            if not observed <= received <= now or now - observed > p["max_quote_age_ms"]:
                failures.add("stale_or_future_quote")
            if not observed <= received <= now or received - observed > p["max_transport_lag_ms"]:
                failures.add("quote_transport_lag")
            if ask > bid and (ask - bid) / ask * 10_000 > spread:
                failures.add("spread_limit")
            observations.append(observed)
            mids.append((bid + ask) / 2)
            rows.append((bid, ask))
        if not primary_seen:
            failures.add("missing_primary_source")
        if max(observations) - min(observations) > p["max_inter_source_skew_ms"]:
            failures.add("inter_source_time_skew")
        if (max(mids) - min(mids)) / max(mids) * 10_000 > divergence:
            failures.add("mid_price_divergence")
        # A feed's bid exceeding another feed's ask can signal stale/misaligned
        # snapshots. A legitimate market may also exhibit this; review, don't trade.
        if max(b for b, _ in rows) >= min(a for _, a in rows):
            failures.add("cross_source_market_inversion")
    return {
        "status": "HOLD_QUOTE_REVIEW" if failures else "DECLARED_QUOTE_CONSENSUS_UNVERIFIED",
        "failed_checks": sorted(failures),
        "source_count": len(quotes),
        "quote_authenticated": False,
        "source_independence_verified": False,
        "broker_authenticated": False,
        "may_submit_paper_order": False,
        "may_submit_real_order": False,
    }
