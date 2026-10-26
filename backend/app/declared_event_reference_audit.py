"""Offline per-event declared CFD cash-reference audit; never broker authentication.

Runs upstream financing/execution/FX/rounding/ledger/category checks first. A
reference manifest is a caller assertion, not a signed broker statement.
No provider calls, persistence, orders or live-execution permissions.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal

from app.declared_split_component_anchor_audit import audit_declared_split_component_anchors

_PROTOCOL = "declared-event-reference-v1"
_KINDS = frozenset(("PNL", "COMMISSION", "FINANCING", "FX_CONVERSION", "REVERSAL"))
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,119}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,79})(?:\.[0-9]{1,50})?\Z")
_FIELDS = frozenset(("event_id", "position_id", "kind", "provider", "venue",
                     "account_alias", "currency", "posted_at", "received_at",
                     "amount_cash", "statement_sha256"))
_POLICY = frozenset(("reference_statement_sha256", "reference_captured_at",
                     "reporting_currency", "reporting_minor_units", "expected_events"))
_MAX_TIME = 8640000000


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _cash(value, units):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact event reference amount")
    amount = Decimal(value)
    if (amount.is_zero() and value.startswith("-")) or -amount.as_tuple().exponent > units:
        raise ValueError("Invalid event reference precision or negative zero")
    return format(amount, "f")


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _freeze(manifest, ledger_policy, component_sha, cutoff, policy):
    if type(manifest) is not dict or type(manifest.get("source")) is not dict:
        raise ValueError("Invalid source manifest")
    source = manifest["source"]
    if not all(_id(source.get(k)) for k in ("provider", "venue", "account_alias")):
        raise ValueError("Invalid source identity")
    if not _sha(component_sha) or not _clock(cutoff):
        raise ValueError("Invalid component fingerprint or cutoff")
    positions = manifest.get("positions")
    if type(positions) is not list or not 1 <= len(positions) <= 256:
        raise ValueError("Invalid position population")
    ids = [p.get("position_id") for p in positions if type(p) is dict]
    if len(ids) != len(positions) or any(not _id(i) for i in ids) or len(set(ids)) != len(ids):
        raise ValueError("Invalid position identifiers")
    if type(ledger_policy) is not dict or type(ledger_policy.get("expected_receipts")) is not list:
        raise ValueError("Invalid ledger census")
    census = {}
    for row in ledger_policy["expected_receipts"]:
        if type(row) is not dict or set(row) != {"position_id", "kind", "count"}:
            raise ValueError("Invalid ledger census row")
        pid, kind, count = row["position_id"], row["kind"], row["count"]
        if (not _id(pid) or pid not in ids or type(kind) is not str or kind not in _KINDS or
            (pid, kind) in census or type(count) is not int or not 0 <= count <= 32):
            raise ValueError("Invalid ledger census scope")
        census[(pid, kind)] = count
    if len(census) != len(ids) * len(_KINDS) or sum(census.values()) > 2048:
        raise ValueError("Incomplete or excessive ledger census")
    if type(policy) is not dict or set(policy) != _POLICY:
        raise ValueError("Invalid event-reference policy schema")
    captured, statement = policy["reference_captured_at"], policy["reference_statement_sha256"]
    currency, units = policy["reporting_currency"], policy["reporting_minor_units"]
    if not _clock(captured) or captured > cutoff or not _sha(statement):
        raise ValueError("Reference unavailable at historical cutoff")
    if type(currency) is not str or re.fullmatch(r"[A-Z]{3}", currency) is None:
        raise ValueError("Invalid reporting currency")
    if type(units) is not int or not 0 <= units <= 6:
        raise ValueError("Invalid minor units")
    events = policy["expected_events"]
    if type(events) is not list or len(events) != sum(census.values()):
        raise ValueError("Incomplete reference-event population")
    seen = set()
    counts = {key: 0 for key in census}
    canonical = []
    for row in events:
        if type(row) is not dict or set(row) != _FIELDS:
            raise ValueError("Invalid event reference row")
        eid, pid, kind = row["event_id"], row["position_id"], row["kind"]
        if not _id(eid) or eid in seen or not _id(pid) or type(kind) is not str or (pid, kind) not in census:
            raise ValueError("Unknown or repeated reference-event identity")
        seen.add(eid)
        counts[(pid, kind)] += 1
        if counts[(pid, kind)] > census[(pid, kind)]:
            raise ValueError("Excess reference-event category")
        if any(row[k] != source[k] for k in ("provider", "venue", "account_alias")):
            raise ValueError("Cross-source reference event")
        if row["currency"] != currency or not _sha(row["statement_sha256"]):
            raise ValueError("Invalid event statement/currency")
        posted, received = row["posted_at"], row["received_at"]
        if not _clock(posted) or not _clock(received) or posted > received or received > captured:
            raise ValueError("Reference event not available when captured")
        canonical.append({**row, "amount_cash": _cash(row["amount_cash"], units)})
    if counts != census:
        raise ValueError("Incomplete per-kind reference census")
    return {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "component_policy_sha256": component_sha,
        "source": {k: source[k] for k in ("provider", "venue", "account_alias")},
        "reference_statement_sha256": statement, "reference_captured_at": captured,
        "reporting_currency": currency, "reporting_minor_units": units,
        "expected_events": sorted(canonical, key=lambda r: r["event_id"]),
    }


def fingerprint_event_reference_policy(manifest, ledger_policy, component_sha, cutoff, policy):
    """Fingerprint declared references; SHA-256 does not authenticate their origin."""
    return _digest(_freeze(manifest, ledger_policy, component_sha, cutoff, policy))


def audit_declared_event_references(
    manifest, financing_versions, expected_financing_sha256,
    specs, expected_specs_sha256, fills, *, cutoff, fx_policy,
    expected_fx_policy_sha256, fx_quotes, rounding_policy,
    expected_rounding_policy_sha256, ledger_policy,
    expected_ledger_policy_sha256, ledger_events, component_policy,
    expected_component_policy_sha256, event_reference_policy,
    expected_event_reference_policy_sha256,
):
    """Withhold net cash on mismatched *individual* declared ledger receipts."""
    frozen = _freeze(manifest, ledger_policy, expected_component_policy_sha256,
                     cutoff, event_reference_policy)
    policy_sha = _digest(frozen)
    if not _sha(expected_event_reference_policy_sha256) or policy_sha != expected_event_reference_policy_sha256:
        raise ValueError("Event reference policy digest mismatch")
    if (frozen["reporting_currency"] != component_policy.get("reporting_currency") or
        frozen["reporting_minor_units"] != component_policy.get("reporting_minor_units") or
        frozen["reference_statement_sha256"] != component_policy.get("reference_statement_sha256") or
        frozen["reference_captured_at"] != component_policy.get("reference_captured_at")):
        raise ValueError("Event and component reference policies disagree")
    upstream = audit_declared_split_component_anchors(
        manifest, financing_versions, expected_financing_sha256,
        specs, expected_specs_sha256, fills, cutoff=cutoff, fx_policy=fx_policy,
        expected_fx_policy_sha256=expected_fx_policy_sha256, fx_quotes=fx_quotes,
        rounding_policy=rounding_policy,
        expected_rounding_policy_sha256=expected_rounding_policy_sha256,
        ledger_policy=ledger_policy,
        expected_ledger_policy_sha256=expected_ledger_policy_sha256,
        ledger_events=ledger_events, component_policy=component_policy,
        expected_component_policy_sha256=expected_component_policy_sha256,
    )
    common = {
        "protocol": _PROTOCOL, "cutoff": cutoff,
        "event_reference_policy_sha256": policy_sha,
        "source_authenticated": False, "broker_settlement_verified": False,
        "untouched_holdout_verified": False, "verified_profitability": False,
        "may_execute_order": False,
    }
    if upstream.get("status") != "COMPLETE_SELF_DECLARED_COMPONENTS_ONLY":
        return {**common, "status": "WITHHELD_UPSTREAM_" + str(upstream.get("status")),
                "reconciled_reporting_cash": None, "event_mismatches": []}
    if (upstream.get("component_policy_sha256") != expected_component_policy_sha256 or
        upstream.get("cutoff") != cutoff or
        upstream.get("source_authenticated") is not False or
        upstream.get("may_execute_order") is not False):
        raise ValueError("Inconsistent upstream component identity")
    reference = {row["event_id"]: row for row in frozen["expected_events"]}
    observed = {}
    for event in ledger_events:
        if type(event) is not dict or set(event) != _FIELDS or not _id(event.get("event_id")):
            raise ValueError("Invalid ledger event after upstream audit")
        eid = event["event_id"]
        if eid in observed:
            raise ValueError("Duplicate ledger event after upstream audit")
        observed[eid] = event
    missing = sorted(set(reference) - set(observed))
    extra = sorted(set(observed) - set(reference))
    mismatches = []
    for eid in sorted(set(reference) & set(observed)):
        expected, actual = reference[eid], observed[eid]
        different = [field for field in sorted(_FIELDS - {"event_id"})
                     if (_cash(actual[field], frozen["reporting_minor_units"])
                         if field == "amount_cash" else actual[field]) != expected[field]]
        if different:
            mismatches.append({"event_id": eid, "fields": different})
    if missing or extra or mismatches:
        return {**common, "status": "MISMATCH_DECLARED_EVENT_REFERENCES",
                "reconciled_reporting_cash": None,
                "missing_event_ids": missing, "extra_event_ids": extra,
                "event_mismatches": mismatches,
                "ledger_declaration_sha256": upstream["ledger_declaration_sha256"]}
    return {**common, "status": "COMPLETE_SELF_DECLARED_EVENTS_ONLY",
            "expected_positions": upstream["expected_positions"],
            "expected_events": len(reference),
            "ledger_declaration_sha256": upstream["ledger_declaration_sha256"],
            "reconciled_reporting_cash": upstream["reconciled_reporting_cash"],
            "event_mismatches": [],
            "warning": "Matching caller-declared event references are not authenticated broker statements, source completeness, or profit evidence."}
