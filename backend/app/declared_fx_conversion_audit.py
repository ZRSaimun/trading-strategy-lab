"""Offline point-in-time FX conversion of declared CFD round-trip cash results.

All quotes and timestamps are self-declared. No provider calls, orders,
cash settlement, market authentication, or profitability inference.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

from app.declared_roundtrip_cost_audit import audit_declared_roundtrip_net

_PROTOCOL = "declared-roundtrip-point-in-time-fx-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_RATE = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,10})?\Z")
_POLICY = frozenset(("fx_provider", "fx_venue", "reporting_currency", "max_quote_age_seconds"))
_QUOTE = frozenset((
    "position_id", "account_alias", "fx_provider", "fx_venue", "base_currency",
    "quote_currency", "quote_id", "observed_at", "received_at", "bid", "ask",
    "source_statement_sha256",
))
_MAX_TIME = 8640000000


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()


def _validate_policy(manifest, policy, financing_sha, specs_sha):
    if type(manifest) is not dict or type(manifest.get("source")) is not dict:
        raise ValueError("Invalid source manifest")
    if type(policy) is not dict or set(policy) != _POLICY:
        raise ValueError("Invalid FX policy schema")
    if not _id(policy["fx_provider"]) or not _id(policy["fx_venue"]):
        raise ValueError("Invalid FX source identity")
    if type(policy["reporting_currency"]) is not str or not _CURRENCY.fullmatch(policy["reporting_currency"]):
        raise ValueError("Invalid reporting currency")
    base = manifest["source"].get("settlement_currency")
    if type(base) is not str or not _CURRENCY.fullmatch(base) or base == policy["reporting_currency"]:
        raise ValueError("FX conversion requires two distinct declared currencies")
    age = policy["max_quote_age_seconds"]
    if type(age) is not int or not 0 <= age <= 3600:
        raise ValueError("Invalid bounded quote freshness policy")
    if not all(type(x) is str and _SHA.fullmatch(x) for x in (financing_sha, specs_sha)):
        raise ValueError("Invalid upstream research digest")
    positions = manifest.get("positions")
    if type(positions) is not list or not 1 <= len(positions) <= 256:
        raise ValueError("Invalid bounded position population")
    seen = set()
    anchors = []
    for row in positions:
        if type(row) is not dict:
            raise ValueError("Invalid position")
        pid, close = row.get("position_id"), row.get("closed_at")
        if not _id(pid) or pid in seen or not _clock(close):
            raise ValueError("Invalid or duplicate FX position anchor")
        seen.add(pid)
        anchors.append({"position_id": pid, "closed_at": close})
    return {
        "protocol": _PROTOCOL,
        "financing_manifest_sha256": financing_sha,
        "roundtrip_specifications_sha256": specs_sha,
        "account_alias": manifest["source"].get("account_alias"),
        "settlement_currency": base,
        "policy": policy,
        "position_close_anchors": sorted(anchors, key=lambda r: r["position_id"]),
    }


def fingerprint_fx_conversion_policy(manifest, policy, financing_sha, specs_sha):
    """Deterministic declaration fingerprint; not a signed pre-outcome freeze."""
    return _digest(_validate_policy(manifest, policy, financing_sha, specs_sha))


def _rate(value):
    if type(value) is not str or _RATE.fullmatch(value) is None:
        raise ValueError("Invalid exact FX rate")
    result = Decimal(value)
    if result <= 0:
        raise ValueError("Nonpositive FX rate")
    return result


def audit_declared_roundtrip_fx(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, fx_policy,
    expected_fx_policy_sha256, fx_quotes,
):
    """Re-audit upstream costs and conservatively translate each position at close.

    Bid converts positive settlement net; ask converts negative net. Quotes
    must be received by position close, not just a later evaluation cutoff.
    """
    freeze = _validate_policy(manifest, fx_policy, expected_financing_sha256, expected_specs_sha256)
    if type(expected_fx_policy_sha256) is not str or not _SHA.fullmatch(expected_fx_policy_sha256):
        raise ValueError("Expected FX policy digest required")
    policy_sha = _digest(freeze)
    if policy_sha != expected_fx_policy_sha256:
        raise ValueError("FX policy digest mismatch")
    upstream = audit_declared_roundtrip_net(
        manifest, financing_versions, expected_financing_sha256,
        specs, expected_specs_sha256, fills, cutoff=cutoff,
    )
    if upstream["status"] != "COMPLETE_SELF_DECLARED_ONLY":
        return {
            "protocol": _PROTOCOL,
            "status": "WITHHELD_INCOMPLETE_UPSTREAM_COSTS",
            "cutoff": cutoff,
            "fx_policy_sha256": policy_sha,
            "net_reporting_cash": None,
            "source_authenticated": False,
            "fx_quotes_authenticated": False,
            "verified_profitability": False,
            "may_execute_order": False,
        }
    positions = {row["position_id"]: row for row in manifest["positions"]}
    if {row["position_id"] for row in upstream["positions"]} != set(positions):
        raise ValueError("Inconsistent upstream position population")
    if type(fx_quotes) is not list or len(fx_quotes) != len(positions):
        raise ValueError("Missing or extra FX quote population")
    seen_positions, quote_ids, by_position = set(), {}, {}
    for quote in fx_quotes:
        if type(quote) is not dict or set(quote) != _QUOTE:
            raise ValueError("Invalid FX quote schema")
        pid = quote["position_id"]
        if pid not in positions or pid in seen_positions:
            raise ValueError("Extra or duplicate FX position quote")
        seen_positions.add(pid)
        if (quote["account_alias"] != manifest["source"]["account_alias"] or
            quote["fx_provider"] != fx_policy["fx_provider"] or
            quote["fx_venue"] != fx_policy["fx_venue"] or
            quote["base_currency"] != manifest["source"]["settlement_currency"] or
            quote["quote_currency"] != fx_policy["reporting_currency"]):
            raise ValueError("Cross-source or inverted FX quote")
        if not _id(quote["quote_id"]) or (
            type(quote["source_statement_sha256"]) is not str or
            _SHA.fullmatch(quote["source_statement_sha256"]) is None
        ):
            raise ValueError("Invalid FX quote evidence identity")
        observed, received, closed = quote["observed_at"], quote["received_at"], positions[pid]["closed_at"]
        if not all(_clock(x) for x in (observed, received, closed)) or not (
            observed <= received <= closed <= cutoff and
            closed - observed <= fx_policy["max_quote_age_seconds"]
        ):
            raise ValueError("Stale, late or future FX quote evidence")
        bid, ask = _rate(quote["bid"]), _rate(quote["ask"])
        if bid > ask:
            raise ValueError("Crossed FX quote")
        signature = (
            quote["account_alias"], quote["fx_provider"], quote["fx_venue"],
            quote["base_currency"], quote["quote_currency"], observed,
            received, bid, ask, quote["source_statement_sha256"],
        )
        if quote["quote_id"] in quote_ids and quote_ids[quote["quote_id"]] != signature:
            raise ValueError("Conflicting reused FX quote ID")
        quote_ids[quote["quote_id"]] = signature
        by_position[pid] = (quote, bid, ask)
    if set(by_position) != set(positions):
        raise ValueError("Incomplete FX position coverage")
    with localcontext() as ctx:
        ctx.prec = 80
        total_mid, total_fx_cost, total_net = Decimal(0), Decimal(0), Decimal(0)
        results = []
        for position in sorted(upstream["positions"], key=lambda r: r["position_id"]):
            pid = position["position_id"]
            quote, bid, ask = by_position[pid]
            net = Decimal(position["net_cash"])
            midpoint = (bid + ask) / 2
            mid_cash = net * midpoint
            converted = net * (bid if net >= 0 else ask)
            fx_cost = mid_cash - converted
            if fx_cost < 0 or mid_cash - fx_cost != converted:
                raise ValueError("Invalid FX conversion decomposition")
            total_mid += mid_cash
            total_fx_cost += fx_cost
            total_net += converted
            results.append({
                "position_id": pid,
                "settlement_net_cash": position["net_cash"],
                "fx_quote_id": quote["quote_id"],
                "fx_observed_at": quote["observed_at"],
                "mid_reporting_cash": format(mid_cash, "f"),
                "fx_half_spread_cost_reporting_cash": format(fx_cost, "f"),
                "net_reporting_cash": format(converted, "f"),
            })
        if total_mid - total_fx_cost != total_net:
            raise ValueError("Aggregate FX decomposition mismatch")
        return {
            "protocol": _PROTOCOL,
            "status": "COMPLETE_SELF_DECLARED_ONLY",
            "cutoff": cutoff,
            "settlement_currency": manifest["source"]["settlement_currency"],
            "reporting_currency": fx_policy["reporting_currency"],
            "fx_policy_sha256": policy_sha,
            "upstream_fill_declaration_sha256": upstream["fill_declaration_sha256"],
            "fx_quote_declaration_sha256": _digest(sorted(fx_quotes, key=lambda q: q["position_id"])),
            "expected_positions": len(positions),
            "positions": results,
            "mid_reporting_cash": format(total_mid, "f"),
            "fx_half_spread_cost_reporting_cash": format(total_fx_cost, "f"),
            "net_reporting_cash": format(total_net, "f"),
            "source_authenticated": False,
            "fx_quotes_authenticated": False,
            "real_execution_costs_verified": False,
            "untouched_holdout_verified": False,
            "verified_profitability": False,
            "may_execute_order": False,
            "warning": (
                "All FX quotes, availability clocks, source hashes, broker fills and financing "
                "are caller-declared. Close-time bid/ask conversion is a conservative hypothetical "
                "valuation, not a booked FX transaction or verified broker settlement. No rounding, "
                "external source authentication, untouched holdout or profitable edge is established."
            ),
        }
