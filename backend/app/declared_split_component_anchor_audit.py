"""Offline per-kind anchors for a caller-declared split CFD cash ledger.

This compares declarations, not independently sourced broker data.
No orders, provider access, persistence, or verified trading results.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

from app.declared_split_cash_ledger_audit import audit_declared_split_cash_ledger

_PROTOCOL = "declared-split-component-anchors-v1"
_KINDS = ("PNL", "COMMISSION", "FINANCING", "FX_CONVERSION", "REVERSAL")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,79})(?:\.[0-9]{1,50})?\Z")
_MAX_TIME = 8640000000


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()


def _cash(value, units):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact component cash")
    number = Decimal(value)
    if (number.is_zero() and value.startswith("-")) or -number.as_tuple().exponent > units:
        raise ValueError("Invalid component cash precision or negative zero")
    return number


def _freeze(manifest, ledger_policy, ledger_sha, cutoff, component_policy):
    if type(manifest) is not dict or type(manifest.get("source")) is not dict:
        raise ValueError("Invalid position manifest")
    source = manifest["source"]
    if not all(type(source.get(k)) is str and _ID.fullmatch(source[k])
               for k in ("provider", "venue", "account_alias")):
        raise ValueError("Invalid source identity")
    if type(ledger_sha) is not str or _SHA.fullmatch(ledger_sha) is None:
        raise ValueError("Invalid ledger policy digest")
    if type(cutoff) is not int or not 0 <= cutoff <= _MAX_TIME:
        raise ValueError("Invalid evaluation cutoff")
    positions = manifest.get("positions")
    if type(positions) is not list or not 1 <= len(positions) <= 256:
        raise ValueError("Invalid position population")
    ids = [p.get("position_id") for p in positions if type(p) is dict]
    if (len(ids) != len(positions) or
        any(type(i) is not str or _ID.fullmatch(i) is None for i in ids) or
        len(set(ids)) != len(ids)):
        raise ValueError("Invalid or repeated position identity")
    if type(ledger_policy) is not dict or type(ledger_policy.get("expected_receipts")) is not list:
        raise ValueError("Invalid ledger census")
    declared_counts = {}
    for row in ledger_policy["expected_receipts"]:
        if type(row) is not dict or set(row) != {"position_id", "kind", "count"}:
            raise ValueError("Invalid ledger census row")
        pid, kind = row["position_id"], row["kind"]
        if type(pid) is not str or type(kind) is not str:
            raise ValueError("Invalid ledger census identity")
        key = (pid, kind)
        if (key in declared_counts or pid not in ids or kind not in _KINDS or
            type(row["count"]) is not int or not 0 <= row["count"] <= 32):
            raise ValueError("Invalid ledger census scope")
        declared_counts[key] = row["count"]
    if len(declared_counts) != len(ids) * len(_KINDS):
        raise ValueError("Incomplete ledger census")
    if type(component_policy) is not dict or set(component_policy) != {
        "reporting_currency", "reporting_minor_units", "reference_statement_sha256",
        "reference_captured_at", "expected_components",
    }:
        raise ValueError("Invalid component policy schema")
    currency = component_policy["reporting_currency"]
    units = component_policy["reporting_minor_units"]
    captured = component_policy["reference_captured_at"]
    statement = component_policy["reference_statement_sha256"]
    if type(currency) is not str or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("Invalid component reporting currency")
    if type(units) is not int or not 0 <= units <= 6:
        raise ValueError("Invalid component minor units")
    if type(statement) is not str or _SHA.fullmatch(statement) is None:
        raise ValueError("Invalid reference statement digest")
    if type(captured) is not int or not 0 <= captured <= cutoff:
        raise ValueError("Reference declaration not available by cutoff")
    anchors = component_policy["expected_components"]
    if type(anchors) is not list or len(anchors) != len(declared_counts):
        raise ValueError("Incomplete component reference population")
    seen = set()
    canonical = []
    with localcontext() as ctx:
        ctx.prec = 160
        for row in anchors:
            if type(row) is not dict or set(row) != {"position_id", "kind", "amount_cash"}:
                raise ValueError("Invalid component anchor row")
            pid, kind = row["position_id"], row["kind"]
            if type(pid) is not str or type(kind) is not str:
                raise ValueError("Invalid component anchor identity")
            key = (pid, kind)
            if key not in declared_counts or key in seen:
                raise ValueError("Unknown or duplicate component anchor")
            seen.add(key)
            amount = _cash(row["amount_cash"], units)
            if declared_counts[key] == 0 and amount != 0:
                raise ValueError("Nonzero reference with zero declared receipts")
            canonical.append({"position_id": pid, "kind": kind,
                              "amount_cash": format(amount, "f")})
    return {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "ledger_policy_sha256": ledger_sha,
        "source": {k: source[k] for k in ("provider", "venue", "account_alias")},
        "reporting_currency": currency, "reporting_minor_units": units,
        "reference_statement_sha256": statement,
        "reference_captured_at": captured,
        "expected_components": sorted(canonical, key=lambda r: (r["position_id"], r["kind"])),
    }


def fingerprint_split_component_policy(manifest, ledger_policy, ledger_sha, cutoff, component_policy):
    """Hash caller-declared anchors; never proof of external statement authenticity."""
    return _digest(_freeze(manifest, ledger_policy, ledger_sha, cutoff, component_policy))


def audit_declared_split_component_anchors(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, fx_policy,
    expected_fx_policy_sha256, fx_quotes, rounding_policy,
    expected_rounding_policy_sha256, ledger_policy,
    expected_ledger_policy_sha256, ledger_events, component_policy,
    expected_component_policy_sha256,
):
    """Reject offsetting category changes against separately declared anchors."""
    frozen = _freeze(manifest, ledger_policy, expected_ledger_policy_sha256,
                     cutoff, component_policy)
    policy_sha = _digest(frozen)
    if (type(expected_component_policy_sha256) is not str or
        _SHA.fullmatch(expected_component_policy_sha256) is None or
        expected_component_policy_sha256 != policy_sha):
        raise ValueError("Component policy digest mismatch")
    if (component_policy["reporting_currency"] != fx_policy.get("reporting_currency") or
        component_policy["reporting_minor_units"] != rounding_policy.get("reporting_minor_units")):
        raise ValueError("Component and FX reporting policy disagree")
    result = audit_declared_split_cash_ledger(
        manifest, financing_versions, expected_financing_sha256,
        specs, expected_specs_sha256, fills, cutoff=cutoff,
        fx_policy=fx_policy, expected_fx_policy_sha256=expected_fx_policy_sha256,
        fx_quotes=fx_quotes, rounding_policy=rounding_policy,
        expected_rounding_policy_sha256=expected_rounding_policy_sha256,
        ledger_policy=ledger_policy,
        expected_ledger_policy_sha256=expected_ledger_policy_sha256,
        ledger_events=ledger_events,
    )
    common = {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "component_policy_sha256": policy_sha,
        "source_authenticated": False, "broker_settlement_verified": False,
        "untouched_holdout_verified": False, "verified_profitability": False,
        "may_execute_order": False,
    }
    if result["status"] != "COMPLETE_SELF_DECLARED_ONLY":
        return {**common, "status": "WITHHELD_UPSTREAM_" + result["status"],
                "reconciled_reporting_cash": None, "component_mismatches": [],
                "upstream_status": result["status"]}
    if (result.get("ledger_policy_sha256") != expected_ledger_policy_sha256 or
        result.get("cutoff") != cutoff or
        result.get("reporting_currency") != frozen["reporting_currency"] or
        result.get("source_authenticated") is not False or
        result.get("may_execute_order") is not False):
        raise ValueError("Inconsistent upstream split ledger identity")
    units = frozen["reporting_minor_units"]
    expected = {(r["position_id"], r["kind"]): _cash(r["amount_cash"], units)
                for r in frozen["expected_components"]}
    observed = {key: Decimal(0) for key in expected}
    with localcontext() as ctx:
        ctx.prec = 160
        for event in ledger_events:
            observed[(event["position_id"], event["kind"])] += _cash(event["amount_cash"], units)
        mismatches = [{
            "position_id": pid, "kind": kind,
            "reference_cash": format(expected[(pid, kind)], "f"),
            "declared_ledger_cash": format(observed[(pid, kind)], "f"),
            "difference_cash": format(observed[(pid, kind)] - expected[(pid, kind)], "f"),
        } for pid, kind in sorted(expected) if observed[(pid, kind)] != expected[(pid, kind)]]
        reference_totals = {pid: Decimal(0) for pid, _ in expected}
        for (pid, _), amount in expected.items():
            reference_totals[pid] += amount
        observed_totals = {pid: Decimal(0) for pid in reference_totals}
        for (pid, _), amount in observed.items():
            observed_totals[pid] += amount
        if any(reference_totals[pid] != observed_totals[pid] for pid in reference_totals):
            mismatches.append({"position_id": "*", "kind": "REFERENCE_NET",
                               "reference_cash": None, "declared_ledger_cash": None,
                               "difference_cash": None})
    if mismatches:
        return {**common, "status": "MISMATCH_DECLARED_COMPONENTS",
                "reconciled_reporting_cash": None, "component_mismatches": mismatches,
                "ledger_declaration_sha256": result["ledger_declaration_sha256"]}
    return {**common, "status": "COMPLETE_SELF_DECLARED_COMPONENTS_ONLY",
            "expected_positions": len(reference_totals),
            "expected_components": len(expected),
            "ledger_declaration_sha256": result["ledger_declaration_sha256"],
            "reconciled_reporting_cash": result["reconciled_reporting_cash"],
            "component_mismatches": [],
            "warning": "Matching self-declared category anchors are not authenticated broker statements or profit evidence."}
