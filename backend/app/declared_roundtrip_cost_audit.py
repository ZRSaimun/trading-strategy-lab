"""Offline, declared-only CFD round-trip fill and financing cost reconciliation.

No broker connection, market-data lookup, order submission or profit claim.
All contract multipliers, quotes, fills, statements and cutoffs are supplied
by the caller. A matching digest is NOT proof of independent preregistration.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

from app.financing_position_population import audit_financing_position_population

_PROTOCOL = "declared-roundtrip-net-cost-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,8})?\Z")
_SPEC = {"position_id", "direction", "quantity", "point_value_cash"}
_FILL = {
    "fill_id", "position_id", "provider", "venue", "account_alias",
    "instrument", "settlement_currency", "phase", "side", "executed_at",
    "received_at", "quote_observed_at", "quote_id", "bid", "ask",
    "fill_price", "quantity", "commission_cash", "execution_statement_sha256",
}
_MAX_TIME = 8640000000


def _exact(row, fields, label):
    if type(row) is not dict or set(row) != fields:
        raise ValueError("Invalid " + label + " schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _number(value, label, *, positive=False):
    if type(value) is not str or _DECIMAL.fullmatch(value) is None:
        raise ValueError("Invalid exact " + label)
    number = Decimal(value)
    if positive and number <= 0:
        raise ValueError("Nonpositive " + label)
    return number


def _digest(obj):
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _canonical_specs(manifest, specs):
    if type(specs) is not list or not 1 <= len(specs) <= 256:
        raise ValueError("Invalid bounded position specifications")
    expected = {p["position_id"] for p in manifest["positions"]}
    by_id = {}
    for spec in specs:
        _exact(spec, _SPEC, "position specification")
        pid = spec["position_id"]
        if not _id(pid) or pid in by_id:
            raise ValueError("Duplicate or invalid position specification")
        if spec["direction"] not in ("LONG", "SHORT"):
            raise ValueError("Invalid direction")
        _number(spec["quantity"], "position quantity", positive=True)
        _number(spec["point_value_cash"], "cash point value", positive=True)
        by_id[pid] = spec
    if set(by_id) != expected:
        raise ValueError("Incomplete or extra position specification")
    return by_id


def fingerprint_roundtrip_specs(manifest, specs, financing_manifest_sha256):
    """Stable specification receipt; not a signed or independently timed freeze."""
    if type(financing_manifest_sha256) is not str or _SHA.fullmatch(financing_manifest_sha256) is None:
        raise ValueError("Financing manifest digest required")
    by_id = _canonical_specs(manifest, specs)
    return _digest({
        "protocol": _PROTOCOL,
        "financing_manifest_sha256": financing_manifest_sha256,
        "specifications": [by_id[k] for k in sorted(by_id)],
    })


def audit_declared_roundtrip_net(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, max_quote_age_seconds=5,
):
    """Reconcile every declared entry/exit fill with point-in-time financing.

    Spread is half the supplied bid/ask width at EACH execution. Signed
    slippage is measured against the executable side (BUY ask / SELL bid).
    Thus mid-price gross P&L minus spread/slippage/commission/financing
    equals execution-price net P&L, without counting spread twice.
    """
    if type(max_quote_age_seconds) is not int or not 0 <= max_quote_age_seconds <= 60:
        raise ValueError("Invalid quote age policy")
    if not _clock(cutoff):
        raise ValueError("Invalid as-of cutoff")
    financing = audit_financing_position_population(
        manifest, financing_versions, expected_financing_sha256
    )
    if cutoff not in manifest["cutoffs"]:
        raise ValueError("Cutoff not registered in financing manifest")
    by_id = _canonical_specs(manifest, specs)
    if type(expected_specs_sha256) is not str or _SHA.fullmatch(expected_specs_sha256) is None:
        raise ValueError("Expected specification digest required")
    spec_digest = fingerprint_roundtrip_specs(manifest, specs, expected_financing_sha256)
    if spec_digest != expected_specs_sha256:
        raise ValueError("Specification digest mismatch")
    if type(fills) is not list or not 1 <= len(fills) <= 4096:
        raise ValueError("Invalid bounded fill population")

    positions = {p["position_id"]: p for p in manifest["positions"]}
    source = manifest["source"]
    grouped = {pid: {"ENTRY": [], "EXIT": []} for pid in by_id}
    fill_ids, quote_ids = set(), {}
    for fill in fills:
        _exact(fill, _FILL, "fill")
        pid = fill["position_id"]
        if pid not in positions or not _id(fill["fill_id"]) or fill["fill_id"] in fill_ids:
            raise ValueError("Unregistered position or duplicate fill ID")
        fill_ids.add(fill["fill_id"])
        position, spec = positions[pid], by_id[pid]
        for key in ("provider", "venue", "account_alias", "settlement_currency"):
            if fill[key] != source[key]:
                raise ValueError("Cross-source fill")
        if fill["instrument"] != position["instrument"]:
            raise ValueError("Cross-instrument fill")
        if fill["phase"] not in ("ENTRY", "EXIT"):
            raise ValueError("Invalid fill phase")
        expected_side = ("BUY" if spec["direction"] == "LONG" else "SELL")
        if fill["phase"] == "EXIT":
            expected_side = "SELL" if expected_side == "BUY" else "BUY"
        if fill["side"] != expected_side:
            raise ValueError("Wrong fill side for position phase")
        if not all(_clock(fill[k]) for k in ("executed_at", "received_at", "quote_observed_at")):
            raise ValueError("Invalid fill evidence clock")
        if not (
            position["opened_at"] <= fill["quote_observed_at"] <= fill["executed_at"]
            <= fill["received_at"] <= cutoff
            and fill["executed_at"] <= position["closed_at"]
            and fill["executed_at"] - fill["quote_observed_at"] <= max_quote_age_seconds
        ):
            raise ValueError("Future, stale or out-of-position fill evidence")
        if not _id(fill["quote_id"]) or not (
            type(fill["execution_statement_sha256"]) is str
            and _SHA.fullmatch(fill["execution_statement_sha256"])
        ):
            raise ValueError("Invalid quote or statement identity")
        bid = _number(fill["bid"], "bid", positive=True)
        ask = _number(fill["ask"], "ask", positive=True)
        price = _number(fill["fill_price"], "fill price", positive=True)
        qty = _number(fill["quantity"], "fill quantity", positive=True)
        commission = _number(fill["commission_cash"], "commission")
        if bid > ask:
            raise ValueError("Crossed quote")
        quote_signature = (
            fill["provider"], fill["venue"], fill["account_alias"],
            fill["instrument"], fill["settlement_currency"],
            fill["quote_observed_at"], bid, ask,
        )
        prior = quote_ids.setdefault(fill["quote_id"], quote_signature)
        if prior != quote_signature:
            raise ValueError("Conflicting reused quote ID")
        grouped[pid][fill["phase"]].append(
            (fill["executed_at"], fill["fill_id"], qty, bid, ask, price, commission, fill["side"])
        )

    snapshot = financing["snapshots"][manifest["cutoffs"].index(cutoff)]
    if snapshot["cutoff"] != cutoff:
        raise ValueError("Financing snapshot cutoff mismatch")
    if snapshot["status"] != "COMPLETE_SELF_DECLARED_ONLY":
        return {
            "protocol": _PROTOCOL,
            "status": "WITHHELD_INCOMPLETE_DECLARED_FINANCING",
            "cutoff": cutoff,
            "missing_or_unverified_positions": snapshot["missing_or_unverified_positions"],
            "net_cash": None,
            "source_authenticated": False,
            "real_execution_costs_verified": False,
            "verified_profitability": False,
            "may_execute_order": False,
        }
    financing_by_id = {r["position_id"]: r for r in snapshot["positions"]}
    if set(financing_by_id) != set(by_id):
        raise ValueError("Financing position identity mismatch")
    results = []
    with localcontext() as ctx:
        ctx.prec = 80
        totals = {k: Decimal(0) for k in (
            "gross_mid_cash", "spread_cash", "signed_slippage_cash",
            "commission_cash", "financing_cash", "net_cash",
        )}
        for pid in sorted(by_id):
            spec = by_id[pid]
            entry, exit_ = grouped[pid]["ENTRY"], grouped[pid]["EXIT"]
            if not entry or not exit_:
                raise ValueError("Missing declared entry or exit fills")
            if min(r[0] for r in entry) != positions[pid]["opened_at"] or (
                max(r[0] for r in exit_) != positions[pid]["closed_at"]
            ) or max(r[0] for r in entry) >= min(r[0] for r in exit_):
                raise ValueError("Invalid entry/exit chronology")
            qty = _number(spec["quantity"], "position quantity", positive=True)
            point = _number(spec["point_value_cash"], "cash point value", positive=True)
            if sum((r[2] for r in entry), Decimal(0)) != qty or (
                sum((r[2] for r in exit_), Decimal(0)) != qty
            ):
                raise ValueError("Incomplete or excess partial fill population")
            def weighted(rows, index):
                return sum((r[index] * r[2] for r in rows), Decimal(0))
            def mid_notional(rows):
                return sum(((r[3] + r[4]) / 2 * r[2] for r in rows), Decimal(0))
            sign = Decimal(1) if spec["direction"] == "LONG" else Decimal(-1)
            gross = sign * (mid_notional(exit_) - mid_notional(entry)) * point
            spread = sum(((r[4] - r[3]) / 2 * r[2] * point for r in entry + exit_), Decimal(0))
            slippage = sum((
                (r[5] - r[4] if r[7] == "BUY" else r[3] - r[5]) * r[2] * point
                for r in entry + exit_
            ), Decimal(0))
            commissions = sum((r[6] for r in entry + exit_), Decimal(0))
            financing_row = financing_by_id[pid]
            if financing_row["status"] != "MATCHED_SELF_DECLARED" or financing_row["declared_total_currency"] is None:
                raise ValueError("Inconsistent complete financing snapshot")
            carry = Decimal(financing_row["declared_total_currency"])
            realized = sign * (weighted(exit_, 5) - weighted(entry, 5)) * point
            net = realized - commissions - carry
            if gross - spread - slippage - commissions - carry != net:
                raise ValueError("Mid-price execution decomposition mismatch")
            values = dict(
                gross_mid_cash=gross, spread_cash=spread,
                signed_slippage_cash=slippage, commission_cash=commissions,
                financing_cash=carry, net_cash=net,
            )
            for key, value in values.items():
                totals[key] += value
            results.append(dict(
                position_id=pid, instrument=positions[pid]["instrument"],
                direction=spec["direction"], entry_fills=len(entry), exit_fills=len(exit_),
                **{key: format(value, "f") for key, value in values.items()},
            ))
        return {
            "protocol": _PROTOCOL,
            "status": "COMPLETE_SELF_DECLARED_ONLY",
            "cutoff": cutoff,
            "expected_positions": len(by_id),
            "declared_fills": len(fills),
            "financing_manifest_sha256": expected_financing_sha256,
            "specifications_sha256": spec_digest,
            "fill_declaration_sha256": _digest(sorted(fills, key=lambda f: f["fill_id"])),
            "positions": results,
            **{key: format(value, "f") for key, value in totals.items()},
            "source_authenticated": False,
            "real_execution_costs_verified": False,
            "contract_multipliers_verified": False,
            "untouched_holdout_verified": False,
            "verified_profitability": False,
            "may_execute_order": False,
            "warning": (
                "Declared source, executable quotes, contract point values, fills, commissions, "
                "financing schedules and revision clocks are unauthenticated. No FX conversion, "
                "settlement rounding, independent preregistration, broker reconciliation, "
                "holdout integrity, statistical edge or order execution is established."
            ),
        }
