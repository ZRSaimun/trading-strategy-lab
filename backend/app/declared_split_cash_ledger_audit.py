"""Offline split-entry CFD cash-ledger census against hypothetical rounded net.

This reconciles caller-declared cash events, not independently authenticated
broker records. No provider calls, order submission, persistence or profit claim.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, localcontext

from app.declared_fx_rounding_sensitivity import audit_declared_fx_rounding

_PROTOCOL = "declared-split-cash-ledger-v1"
_KINDS = ("PNL", "COMMISSION", "FINANCING", "FX_CONVERSION", "REVERSAL")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,79})(?:\.[0-9]{1,50})?\Z")
_POLICY = {"max_posting_delay_seconds", "max_receipt_lag_seconds", "expected_receipts"}
_EVENT = {
    "event_id", "position_id", "provider", "venue", "account_alias",
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


def _cash(value, units):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact ledger cash")
    amount = Decimal(value)
    if amount.is_zero() and value.startswith("-"):
        raise ValueError("Negative-zero ledger cash")
    if -amount.as_tuple().exponent > units:
        raise ValueError("Ledger cash exceeds reporting minor units")
    return amount


def _freeze(manifest, fx_policy, fx_sha, rounding_sha, cutoff, policy):
    if type(manifest) is not dict or type(manifest.get("source")) is not dict:
        raise ValueError("Invalid source manifest")
    source = manifest["source"]
    if not all(_id(source.get(k)) for k in ("provider", "venue", "account_alias")):
        raise ValueError("Invalid broker source identity")
    if type(fx_policy) is not dict or type(fx_policy.get("reporting_currency")) is not str:
        raise ValueError("Invalid FX reporting policy")
    currency = fx_policy["reporting_currency"]
    if re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("Invalid reporting currency")
    if not _sha(fx_sha) or not _sha(rounding_sha) or not _clock(cutoff):
        raise ValueError("Invalid upstream digest or evaluation cutoff")
    positions = manifest.get("positions")
    if type(positions) is not list or not 1 <= len(positions) <= 256:
        raise ValueError("Invalid bounded position population")
    anchors = {}
    for p in positions:
        if type(p) is not dict or not _id(p.get("position_id")):
            raise ValueError("Invalid position ID")
        pid, opened, closed = p["position_id"], p.get("opened_at"), p.get("closed_at")
        if pid in anchors or not _clock(opened) or not _clock(closed) or not opened < closed <= cutoff:
            raise ValueError("Duplicate, future or invalid position clock")
        anchors[pid] = {"position_id": pid, "opened_at": opened, "closed_at": closed}
    if type(policy) is not dict or set(policy) != _POLICY:
        raise ValueError("Invalid split-ledger policy schema")
    for k in ("max_posting_delay_seconds", "max_receipt_lag_seconds"):
        if type(policy[k]) is not int or not 0 <= policy[k] <= _MAX_DELAY:
            raise ValueError("Invalid bounded posting/receipt lag policy")
    census = policy["expected_receipts"]
    if type(census) is not list or len(census) != len(anchors) * len(_KINDS):
        raise ValueError("Incomplete declared ledger-kind census")
    counts = {}
    for row in census:
        if type(row) is not dict or set(row) != {"position_id", "kind", "count"}:
            raise ValueError("Invalid ledger-kind census row")
        pid, kind, count = row["position_id"], row["kind"], row["count"]
        key = (pid, kind)
        if pid not in anchors or kind not in _KINDS or key in counts:
            raise ValueError("Extra or repeated ledger-kind census")
        if type(count) is not int or not 0 <= count <= 32:
            raise ValueError("Invalid bounded ledger-kind count")
        counts[key] = count
    if any(counts[(pid, "PNL")] < 1 for pid in anchors):
        raise ValueError("At least one PNL receipt required for every position")
    if any(sum(counts[(pid, kind)] for kind in _KINDS) > 32 for pid in anchors):
        raise ValueError("Unbounded per-position ledger census")
    if sum(counts.values()) > 2048:
        raise ValueError("Unbounded aggregate ledger census")
    return {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "fx_policy_sha256": fx_sha, "rounding_policy_sha256": rounding_sha,
        "source": {k: source[k] for k in ("provider", "venue", "account_alias")},
        "reporting_currency": currency,
        "position_anchors": [anchors[k] for k in sorted(anchors)],
        "posting_policy": {
            "max_posting_delay_seconds": policy["max_posting_delay_seconds"],
            "max_receipt_lag_seconds": policy["max_receipt_lag_seconds"],
            "expected_receipts": [
                {"position_id": pid, "kind": kind, "count": counts[(pid, kind)]}
                for pid in sorted(anchors) for kind in _KINDS
            ],
        },
    }


def fingerprint_split_ledger_policy(manifest, fx_policy, fx_sha, rounding_sha, cutoff, policy):
    """Stable *declared* policy fingerprint, not a trusted preregistration."""
    return _digest(_freeze(manifest, fx_policy, fx_sha, rounding_sha, cutoff, policy))


def audit_declared_split_cash_ledger(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, fx_policy,
    expected_fx_policy_sha256, fx_quotes, rounding_policy,
    expected_rounding_policy_sha256, ledger_policy,
    expected_ledger_policy_sha256, ledger_events,
):
    """Re-audit costs and compare a complete declared split-entry ledger census.

    Missing events or upstream evidence withhold all net cash. Matching
    self-declared ledger amounts never authenticate brokerage settlement.
    """
    frozen = _freeze(
        manifest, fx_policy, expected_fx_policy_sha256,
        expected_rounding_policy_sha256, cutoff, ledger_policy,
    )
    policy_sha = _digest(frozen)
    if not _sha(expected_ledger_policy_sha256) or expected_ledger_policy_sha256 != policy_sha:
        raise ValueError("Split-ledger policy digest mismatch")
    upstream = audit_declared_fx_rounding(
        manifest, financing_versions, expected_financing_sha256,
        specs, expected_specs_sha256, fills, cutoff=cutoff,
        fx_policy=fx_policy, expected_fx_policy_sha256=expected_fx_policy_sha256,
        fx_quotes=fx_quotes, rounding_policy=rounding_policy,
        expected_rounding_policy_sha256=expected_rounding_policy_sha256,
    )
    common = {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "ledger_policy_sha256": policy_sha,
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
        upstream.get("reporting_currency") != frozen["reporting_currency"] or
        upstream.get("may_execute_order") is not False or
        upstream.get("source_authenticated") is not False or
        upstream.get("broker_settlement_verified") is not False
    ):
        raise ValueError("Inconsistent upstream FX rounding identity")
    units = rounding_policy["reporting_minor_units"]
    if type(units) is not int or not 0 <= units <= 6:
        raise ValueError("Invalid reporting minor units")
    expected_ids = {p["position_id"] for p in frozen["position_anchors"]}
    rows = upstream.get("positions")
    if type(rows) is not list or len(rows) != len(expected_ids) or upstream.get("expected_positions") != len(expected_ids):
        raise ValueError("Incomplete upstream rounded position population")
    if type(ledger_events) is not list or len(ledger_events) > 2048:
        raise ValueError("Unbounded declared ledger events")
    counts = {
        (r["position_id"], r["kind"]): r["count"]
        for r in frozen["posting_policy"]["expected_receipts"]
    }
    anchors = {r["position_id"]: r for r in frozen["position_anchors"]}
    observed = {key: 0 for key in counts}
    by_position = {pid: [] for pid in expected_ids}
    event_ids = set()
    with localcontext() as ctx:
        ctx.prec = 160
        expected = {}
        total = Decimal(0)
        for row in rows:
            if type(row) is not dict or not _id(row.get("position_id")):
                raise ValueError("Invalid upstream rounded position")
            pid = row["position_id"]
            if pid not in expected_ids or pid in expected:
                raise ValueError("Extra or duplicate upstream position")
            amount = _cash(row.get("rounded_cash"), units)
            expected[pid] = amount
            total += amount
        if set(expected) != expected_ids or total != _cash(upstream.get("rounded_net_reporting_cash"), units):
            raise ValueError("Upstream rounded aggregate mismatch")
        for event in ledger_events:
            if type(event) is not dict or set(event) != _EVENT:
                raise ValueError("Invalid split-ledger event schema")
            pid, kind, eid = event["position_id"], event["kind"], event["event_id"]
            if pid not in anchors or kind not in _KINDS or not _id(eid) or eid in event_ids:
                raise ValueError("Unknown ledger scope or duplicate event ID")
            event_ids.add(eid)
            if (
                any(event[k] != frozen["source"][k] for k in ("provider", "venue", "account_alias")) or
                event["currency"] != frozen["reporting_currency"] or
                not _sha(event["statement_sha256"])
            ):
                raise ValueError("Cross-source, currency or statement identity")
            posted, received = event["posted_at"], event["received_at"]
            opened, closed = anchors[pid]["opened_at"], anchors[pid]["closed_at"]
            if (
                not _clock(posted) or not _clock(received) or
                not opened <= posted <= received <= cutoff or
                (kind in ("PNL", "REVERSAL") and posted < closed) or
                posted - closed > ledger_policy["max_posting_delay_seconds"] or
                received - posted > ledger_policy["max_receipt_lag_seconds"]
            ):
                raise ValueError("Late, future or out-of-position ledger event")
            amount = _cash(event["amount_cash"], units)
            key = (pid, kind)
            observed[key] += 1
            if observed[key] > counts[key]:
                raise ValueError("Undeclared extra split-ledger event")
            by_position[pid].append((event, amount))
        missing = [
            {"position_id": pid, "kind": kind, "missing": counts[(pid, kind)] - observed[(pid, kind)]}
            for pid, kind in sorted(counts) if observed[(pid, kind)] < counts[(pid, kind)]
        ]
        if missing:
            return {
                **common, "status": "WITHHELD_INCOMPLETE_DECLARED_LEDGER",
                "expected_events": sum(counts.values()),
                "observed_events": len(ledger_events),
                "missing": missing,
                "reconciled_reporting_cash": None, "mismatches": [],
            }
        mismatches = []
        for pid in sorted(expected):
            posted_net = sum((amount for _, amount in by_position[pid]), Decimal(0))
            if posted_net != expected[pid]:
                mismatches.append({
                    "position_id": pid,
                    "hypothetical_rounded_cash": format(expected[pid], "f"),
                    "declared_ledger_cash": format(posted_net, "f"),
                    "difference_cash": format(posted_net - expected[pid], "f"),
                })
        canonical_events = [
            event for pid in sorted(by_position)
            for event, _ in sorted(by_position[pid], key=lambda item: (item[0]["kind"], item[0]["event_id"]))
        ]
        receipt_sha = _digest(canonical_events)
        if mismatches:
            return {
                **common, "status": "MISMATCH_DECLARED_LEDGER",
                "expected_events": sum(counts.values()),
                "ledger_declaration_sha256": receipt_sha,
                "reconciled_reporting_cash": None, "mismatches": mismatches,
            }
        return {
            **common, "status": "COMPLETE_SELF_DECLARED_ONLY",
            "expected_positions": len(expected_ids),
            "expected_events": sum(counts.values()),
            "reporting_currency": frozen["reporting_currency"],
            "ledger_declaration_sha256": receipt_sha,
            "reconciled_reporting_cash": format(total, "f"),
            "mismatches": [],
            "warning": (
                "Ledger events, expected counts, timestamps, hashes and component "
                "labels are caller declarations. Net agreement does not verify "
                "broker statements, component correctness or trading profitability."
            ),
        }
