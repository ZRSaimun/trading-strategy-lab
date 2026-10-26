"""Offline sensitivity of declared CFD FX cash to hypothetical rounding.

No broker settlement, authenticated data, orders or profit inference.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext

from app.declared_fx_conversion_audit import audit_declared_roundtrip_fx

_PROTOCOL = "declared-fx-rounding-sensitivity-v1"
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,79})(?:\.[0-9]{1,50})?\Z")
_MODES = {"HALF_EVEN": ROUND_HALF_EVEN, "HALF_UP": ROUND_HALF_UP, "TOWARD_ZERO": ROUND_DOWN}
_MAX_TIME = 8640000000


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _policy_payload(fx_policy_sha, cutoff, policy):
    if not _sha(fx_policy_sha):
        raise ValueError("Missing upstream FX policy fingerprint")
    if type(cutoff) is not int or not 0 <= cutoff <= _MAX_TIME:
        raise ValueError("Invalid historical evaluation cutoff")
    if type(policy) is not dict or set(policy) != {"reporting_minor_units", "rounding_mode"}:
        raise ValueError("Invalid rounding policy schema")
    units = policy["reporting_minor_units"]
    if type(units) is not int or not 0 <= units <= 6:
        raise ValueError("Invalid reporting minor units")
    if type(policy["rounding_mode"]) is not str or policy["rounding_mode"] not in _MODES:
        raise ValueError("Invalid rounding mode")
    return {"protocol": _PROTOCOL, "fx_policy_sha256": fx_policy_sha,
            "evaluation_cutoff": cutoff, "rounding_policy": policy}


def fingerprint_fx_rounding_policy(fx_policy_sha, cutoff, policy):
    """Integrity-only fingerprint; not proof of pre-outcome registration."""
    return _digest(_policy_payload(fx_policy_sha, cutoff, policy))


def _cash(value):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact cash value")
    return Decimal(value)


def audit_declared_fx_rounding(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, fx_policy,
    expected_fx_policy_sha256, fx_quotes, rounding_policy,
    expected_rounding_policy_sha256,
):
    """Recompute declared FX net and compare two hypothetical rounding conventions."""
    payload = _policy_payload(expected_fx_policy_sha256, cutoff, rounding_policy)
    if not _sha(expected_rounding_policy_sha256) or _digest(payload) != expected_rounding_policy_sha256:
        raise ValueError("Rounding policy digest mismatch")
    upstream = audit_declared_roundtrip_fx(
        manifest, financing_versions, expected_financing_sha256,
        specs, expected_specs_sha256, fills, cutoff=cutoff,
        fx_policy=fx_policy, expected_fx_policy_sha256=expected_fx_policy_sha256,
        fx_quotes=fx_quotes,
    )
    common = {"protocol": _PROTOCOL, "cutoff": cutoff,
              "fx_policy_sha256": expected_fx_policy_sha256,
              "rounding_policy_sha256": expected_rounding_policy_sha256,
              "source_authenticated": False, "broker_settlement_verified": False,
              "untouched_holdout_verified": False, "verified_profitability": False,
              "may_execute_order": False}
    if upstream["status"] != "COMPLETE_SELF_DECLARED_ONLY":
        return {**common, "status": "WITHHELD_INCOMPLETE_UPSTREAM_FX",
                "rounded_net_reporting_cash": None, "rounding_delta_reporting_cash": None}
    if (upstream.get("protocol") != "declared-roundtrip-point-in-time-fx-v1" or
        upstream.get("fx_policy_sha256") != expected_fx_policy_sha256 or
        upstream.get("cutoff") != cutoff or
        upstream.get("may_execute_order") is not False or
        upstream.get("source_authenticated") is not False or
        upstream.get("fx_quotes_authenticated") is not False):
        raise ValueError("Inconsistent upstream FX audit identity")
    rows = upstream.get("positions")
    expected = upstream.get("expected_positions")
    if (type(rows) is not list or type(expected) is not int or
        not 1 <= expected <= 256 or len(rows) != expected):
        raise ValueError("Incomplete upstream FX position population")
    seen = set()
    with localcontext() as ctx:
        ctx.prec = 160
        quantum = Decimal(1).scaleb(-rounding_policy["reporting_minor_units"])
        mode = _MODES[rounding_policy["rounding_mode"]]
        total = Decimal(0)
        rounded_sum = Decimal(0)
        positions = []
        for row in sorted(rows, key=lambda r: r.get("position_id", "") if type(r) is dict else ""):
            if type(row) is not dict or type(row.get("position_id")) is not str:
                raise ValueError("Invalid upstream FX position")
            pid = row["position_id"]
            if not pid or pid in seen:
                raise ValueError("Duplicate upstream FX position")
            seen.add(pid)
            raw = _cash(row.get("net_reporting_cash"))
            rounded = raw.quantize(quantum, rounding=mode)
            total += raw
            rounded_sum += rounded
            positions.append({"position_id": pid, "unrounded_cash": format(raw, "f"),
                              "rounded_cash": format(rounded, "f"),
                              "rounding_delta_cash": format(rounded - raw, "f")})
        if total != _cash(upstream.get("net_reporting_cash")):
            raise ValueError("Upstream FX aggregate does not reconcile")
        aggregate_rounded = total.quantize(quantum, rounding=mode)
        delta = rounded_sum - total
        discrepancy = rounded_sum - aggregate_rounded
        if delta != sum((Decimal(p["rounding_delta_cash"]) for p in positions), Decimal(0)):
            raise ValueError("Rounding reconciliation failed")
        return {**common, "status": "COMPLETE_HYPOTHETICAL_ONLY",
                "reporting_currency": upstream["reporting_currency"],
                "expected_positions": expected, "positions": positions,
                "unrounded_net_reporting_cash": format(total, "f"),
                "rounded_net_reporting_cash": format(rounded_sum, "f"),
                "rounding_delta_reporting_cash": format(delta, "f"),
                "aggregate_only_rounded_cash": format(aggregate_rounded, "f"),
                "per_position_minus_aggregate_rounded_cash": format(discrepancy, "f"),
                "fx_quote_declaration_sha256": upstream["fx_quote_declaration_sha256"],
                "warning": "Declared-only rounding sensitivity, not broker settlement or verified P&L."}
