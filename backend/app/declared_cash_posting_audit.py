"""Offline reconciliation of declared position-net FX cash with declared postings.

One NET_CLOSE cash posting per closed position is an explicit modelling
assumption, NOT a claim about any actual broker's statement layout.
No provider access, order submission, broker authentication or profit claim.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

from app.declared_fx_rounding_sensitivity import audit_declared_fx_rounding

_PROTOCOL = "declared-position-net-cash-posting-v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,79})(?:\.[0-9]{1,50})?\Z")
_POLICY_KEYS = {"max_posting_delay_seconds", "max_receipt_lag_seconds"}
_RECEIPT_KEYS = {
    "receipt_id", "position_id", "provider", "venue", "account_alias",
    "currency", "kind", "posted_at", "received_at", "amount_cash",
    "statement_sha256",
}
_MAX_TIME = 8640000000
_MAX_DELAY = 30 * 86400


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _digest(value):
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")).hexdigest()


def _money(value, minor_units):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact posted cash")
    amount = Decimal(value)
    if amount.is_zero() and value.startswith("-"):
        raise ValueError("Negative-zero cash posting")
    if -amount.as_tuple().exponent > minor_units:
        raise ValueError("Posted cash has more than declared minor units")
    return amount


def _freeze(manifest, fx_policy, fx_sha, rounding_sha, cutoff, posting_policy):
    if type(manifest) is not dict or type(manifest.get("source")) is not dict:
        raise ValueError("Invalid source manifest")
    if not _sha(fx_sha) or not _sha(rounding_sha) or not _clock(cutoff):
        raise ValueError("Invalid upstream identity or cutoff")
    if type(fx_policy) is not dict or type(fx_policy.get("reporting_currency")) is not str:
        raise ValueError("Invalid reporting FX policy")
    currency = fx_policy["reporting_currency"]
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("Invalid reporting currency")
    source = manifest["source"]
    if not all(_id(source.get(k)) for k in ("provider", "venue", "account_alias")):
        raise ValueError("Invalid broker source identity")
    positions = manifest.get("positions")
    if type(positions) is not list or not 1 <= len(positions) <= 256:
        raise ValueError("Invalid expected position population")
    anchors, seen = [], set()
    for p in positions:
        if type(p) is not dict or not _id(p.get("position_id")) or not _clock(p.get("closed_at")):
            raise ValueError("Invalid position close anchor")
        if p["position_id"] in seen or p["closed_at"] > cutoff:
            raise ValueError("Duplicate or future position close")
        seen.add(p["position_id"])
        anchors.append({"position_id": p["position_id"], "closed_at": p["closed_at"]})
    if type(posting_policy) is not dict or set(posting_policy) != _POLICY_KEYS:
        raise ValueError("Invalid cash posting policy schema")
    for key in _POLICY_KEYS:
        value = posting_policy[key]
        if type(value) is not int or not 0 <= value <= _MAX_DELAY:
            raise ValueError("Invalid bounded cash posting timing policy")
    return {
        "protocol": _PROTOCOL, "fx_policy_sha256": fx_sha,
        "rounding_policy_sha256": rounding_sha, "cutoff": cutoff,
        "source": {k: source[k] for k in ("provider", "venue", "account_alias")},
        "reporting_currency": currency,
        "position_close_anchors": sorted(anchors, key=lambda p: p["position_id"]),
        "posting_policy": posting_policy,
    }


def fingerprint_cash_posting_policy(
    manifest, fx_policy, fx_sha, rounding_sha, cutoff, posting_policy,
):
    """Caller-declared digest; NOT a broker signature or preregistration."""
    return _digest(_freeze(manifest, fx_policy, fx_sha, rounding_sha, cutoff, posting_policy))


def audit_declared_cash_postings(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, fx_policy,
    expected_fx_policy_sha256, fx_quotes, rounding_policy,
    expected_rounding_policy_sha256, posting_policy,
    expected_posting_policy_sha256, postings,
):
    """Compare a fully re-audited hypothetical net with declared NET_CLOSE postings.

    Missing evidence or a mismatch WITHHOLDS aggregate reconciliation.
    A matching caller-supplied statement hash does not authenticate a broker.
    """
    freeze = _freeze(
        manifest, fx_policy, expected_fx_policy_sha256,
        expected_rounding_policy_sha256, cutoff, posting_policy,
    )
    policy_sha = _digest(freeze)
    if not _sha(expected_posting_policy_sha256) or policy_sha != expected_posting_policy_sha256:
        raise ValueError("Cash posting policy digest mismatch")
    upstream = audit_declared_fx_rounding(
        manifest, financing_versions, expected_financing_sha256,
        specs, expected_specs_sha256, fills, cutoff=cutoff,
        fx_policy=fx_policy, expected_fx_policy_sha256=expected_fx_policy_sha256,
        fx_quotes=fx_quotes, rounding_policy=rounding_policy,
        expected_rounding_policy_sha256=expected_rounding_policy_sha256,
    )
    common = {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "posting_policy_sha256": policy_sha,
        "source_authenticated": False, "broker_settlement_verified": False,
        "untouched_holdout_verified": False, "verified_profitability": False,
        "may_execute_order": False,
    }
    if upstream.get("status") != "COMPLETE_HYPOTHETICAL_ONLY":
        return {
            **common, "status": "WITHHELD_INCOMPLETE_UPSTREAM",
            "reconciled_reporting_cash": None, "mismatches": [],
        }
    if (
        upstream.get("fx_policy_sha256") != expected_fx_policy_sha256 or
        upstream.get("rounding_policy_sha256") != expected_rounding_policy_sha256 or
        upstream.get("cutoff") != cutoff or
        upstream.get("reporting_currency") != fx_policy["reporting_currency"] or
        upstream.get("may_execute_order") is not False or
        upstream.get("broker_settlement_verified") is not False or
        upstream.get("source_authenticated") is not False
    ):
        raise ValueError("Inconsistent upstream rounding identity")
    rows = upstream.get("positions")
    expected_ids = {p["position_id"] for p in manifest["positions"]}
    if (
        type(rows) is not list or len(rows) != len(expected_ids) or
        upstream.get("expected_positions") != len(expected_ids)
    ):
        raise ValueError("Incomplete upstream rounded position population")
    minor_units = rounding_policy["reporting_minor_units"]
    if type(minor_units) is not int or not 0 <= minor_units <= 6:
        raise ValueError("Invalid upstream reporting minor units")
    expected, total = {}, Decimal(0)
    with localcontext() as ctx:
        ctx.prec = 160
        for row in rows:
            if type(row) is not dict or not _id(row.get("position_id")):
                raise ValueError("Invalid upstream rounded position")
            pid = row["position_id"]
            if pid not in expected_ids or pid in expected:
                raise ValueError("Duplicate or extra upstream rounded position")
            cash = _money(row.get("rounded_cash"), minor_units)
            expected[pid] = cash
            total += cash
        if set(expected) != expected_ids or total != _money(
            upstream.get("rounded_net_reporting_cash"), minor_units
        ):
            raise ValueError("Upstream rounded aggregate mismatch")
        if type(postings) is not list or len(postings) > 256:
            raise ValueError("Unbounded declared cash posting population")
        by_position, receipt_ids = {}, set()
        anchors = {p["position_id"]: p["closed_at"] for p in manifest["positions"]}
        for row in postings:
            if type(row) is not dict or set(row) != _RECEIPT_KEYS:
                raise ValueError("Invalid cash posting receipt schema")
            pid, receipt_id = row["position_id"], row["receipt_id"]
            if pid not in expected_ids or pid in by_position:
                raise ValueError("Extra or duplicate position posting")
            if not _id(receipt_id) or receipt_id in receipt_ids:
                raise ValueError("Invalid or reused cash receipt ID")
            receipt_ids.add(receipt_id)
            if (
                any(row[k] != manifest["source"][k] for k in
                    ("provider", "venue", "account_alias")) or
                row["currency"] != fx_policy["reporting_currency"] or
                row["kind"] != "NET_CLOSE"
            ):
                raise ValueError("Cross-source, currency or posting-kind mismatch")
            if not _sha(row["statement_sha256"]):
                raise ValueError("Invalid declared cash statement identity")
            posted, received, closed = row["posted_at"], row["received_at"], anchors[pid]
            if (
                not _clock(posted) or not _clock(received) or
                not closed <= posted <= received <= cutoff or
                posted - closed > posting_policy["max_posting_delay_seconds"] or
                received - posted > posting_policy["max_receipt_lag_seconds"]
            ):
                raise ValueError("Late, future or out-of-window cash posting")
            amount = _money(row["amount_cash"], minor_units)
            by_position[pid] = (row, amount)
        if set(by_position) != expected_ids:
            return {
                **common, "status": "WITHHELD_INCOMPLETE_DECLARED_POSTINGS",
                "expected_positions": len(expected_ids),
                "observed_positions": len(by_position),
                "missing_position_ids": sorted(expected_ids - set(by_position)),
                "reconciled_reporting_cash": None, "mismatches": [],
            }
        mismatches = []
        for pid in sorted(expected):
            amount = by_position[pid][1]
            if amount != expected[pid]:
                mismatches.append({
                    "position_id": pid, "hypothetical_rounded_cash": format(expected[pid], "f"),
                    "declared_posted_cash": format(amount, "f"),
                    "difference_cash": format(amount - expected[pid], "f"),
                })
        receipt_sha = _digest([by_position[pid][0] for pid in sorted(by_position)])
        if mismatches:
            return {
                **common, "status": "MISMATCH_DECLARED_POSTINGS",
                "expected_positions": len(expected_ids),
                "receipt_declaration_sha256": receipt_sha,
                "reconciled_reporting_cash": None, "mismatches": mismatches,
            }
        return {
            **common, "status": "COMPLETE_SELF_DECLARED_ONLY",
            "expected_positions": len(expected_ids),
            "reporting_currency": fx_policy["reporting_currency"],
            "receipt_declaration_sha256": receipt_sha,
            "reconciled_reporting_cash": format(total, "f"),
            "mismatches": [],
            "warning": "Declared postings only; no broker authentication, execution or profit evidence.",
        }
