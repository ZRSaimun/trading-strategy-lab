"""Offline full-declared-position CFD financing reconciliation (no execution).

All source, position, rollover and revision metadata is caller-declared.
A complete result never authenticates a broker or establishes profitability.
"""

import hashlib
import json
import re
from decimal import Decimal, localcontext

from app.financing_vintage_audit import audit_financing_vintages

_PROTOCOL = "declared-financing-position-population-v1"
_ID = re.compile(r"[A-Za-z0-9._:-]{1,120}\Z")
_CURRENCY = re.compile(r"[A-Z]{3}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_SOURCE_KEYS = {"provider", "venue", "account_alias", "settlement_currency"}
_POSITION_KEYS = {"position_id", "instrument", "opened_at", "closed_at", "audit_asof", "required_rollovers"}
_MANIFEST_KEYS = {"protocol", "source", "positions", "cutoffs"}
_MAX_EPOCH = 8640000000


def _exact(obj, keys, name):
    if type(obj) is not dict or set(obj) != keys:
        raise ValueError(f"Invalid {name} schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_EPOCH


def _canonical_sha(obj):
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _validate_manifest(manifest):
    _exact(manifest, _MANIFEST_KEYS, "financing population manifest")
    if manifest["protocol"] != _PROTOCOL:
        raise ValueError("Unknown financing population protocol")
    source = manifest["source"]
    _exact(source, _SOURCE_KEYS, "financing population source")
    if not all(_id(source[k]) for k in ("provider", "venue", "account_alias")):
        raise ValueError("Invalid financing population source identity")
    if type(source["settlement_currency"]) is not str or not _CURRENCY.fullmatch(source["settlement_currency"]):
        raise ValueError("Invalid financing population settlement currency")
    positions = manifest["positions"]
    if type(positions) is not list or not 1 <= len(positions) <= 256:
        raise ValueError("Invalid bounded expected position population")
    ids = set()
    total_rollovers = 0
    for row in positions:
        _exact(row, _POSITION_KEYS, "expected financing position")
        if not _id(row["position_id"]) or row["position_id"] in ids or not _id(row["instrument"]):
            raise ValueError("Duplicate or invalid expected financing position")
        ids.add(row["position_id"])
        if not all(_clock(row[k]) for k in ("opened_at", "closed_at", "audit_asof")) or not (
            row["opened_at"] < row["closed_at"] <= row["audit_asof"]
        ):
            raise ValueError("Invalid expected position clocks")
        rollovers = row["required_rollovers"]
        if type(rollovers) is not list or len(rollovers) > 5000:
            raise ValueError("Invalid declared rollover population")
        total_rollovers += len(rollovers)
        previous = -1
        for rollover in rollovers:
            if not _clock(rollover) or not row["opened_at"] <= rollover < row["closed_at"] or rollover <= previous:
                raise ValueError("Invalid, duplicate or unsorted declared rollover")
            previous = rollover
    if total_rollovers > 10000:
        raise ValueError("Unbounded aggregate declared rollover population")
    cutoffs = manifest["cutoffs"]
    if type(cutoffs) is not list or not 1 <= len(cutoffs) <= 32:
        raise ValueError("Invalid financing population cutoffs")
    first_allowed = max(p["closed_at"] for p in positions)
    last_allowed = min(p["audit_asof"] for p in positions)
    previous = -1
    for cutoff in cutoffs:
        if not _clock(cutoff) or not first_allowed <= cutoff <= last_allowed or cutoff <= previous:
            raise ValueError("Cutoffs must be strictly increasing and after every position closes")
        previous = cutoff
    return {p["position_id"]: p for p in positions}


def fingerprint_financing_position_population(manifest):
    """Digest expected membership/schedules; NOT an external preregistration."""
    _validate_manifest(manifest)
    canonical = dict(
        protocol=_PROTOCOL,
        source=manifest["source"],
        positions=sorted(manifest["positions"], key=lambda p: p["position_id"]),
        cutoffs=manifest["cutoffs"],
    )
    return _canonical_sha(canonical)


def audit_financing_position_population(manifest, versions, expected_manifest_sha256):
    """Reconcile *every declared closed position* at each point-in-time cutoff.

    A single missing receipt, position, or no-due rollover schedule withholds
    the complete portfolio financing total. Never infer a free rollover.
    """
    expected = _validate_manifest(manifest)
    if type(expected_manifest_sha256) is not str or _SHA.fullmatch(expected_manifest_sha256) is None:
        raise ValueError("Expected population digest required")
    digest = fingerprint_financing_position_population(manifest)
    if digest != expected_manifest_sha256:
        raise ValueError("Expected position population digest mismatch")
    if type(versions) is not list or len(versions) > 10000:
        raise ValueError("Invalid bounded financing receipt population")
    grouped = {key: [] for key in expected}
    receipt_ids = set()
    for row in versions:
        if type(row) is not dict or not _id(row.get("position_id")) or row["position_id"] not in expected:
            raise ValueError("Unregistered or invalid financing receipt position")
        if not _id(row.get("receipt_id")) or row["receipt_id"] in receipt_ids:
            raise ValueError("Duplicate or invalid cross-position receipt ID")
        receipt_ids.add(row["receipt_id"])
        grouped[row["position_id"]].append(row)

    reports = {}
    for position_id, position in sorted(expected.items()):
        scope = dict(manifest["source"], position_id=position_id,
                     instrument=position["instrument"], opened_at=position["opened_at"],
                     closed_at=position["closed_at"], audit_asof=position["audit_asof"],
                     required_rollovers=position["required_rollovers"])
        reports[position_id] = audit_financing_vintages(scope, grouped[position_id], manifest["cutoffs"])

    snapshots = []
    with localcontext() as context:
        context.prec = 80
        for index, cutoff in enumerate(manifest["cutoffs"]):
            total = Decimal(0)
            missing = []
            details = []
            for position_id in sorted(expected):
                row = reports[position_id]["snapshots"][index]
                if row["cutoff"] != cutoff:
                    raise ValueError("Inconsistent upstream financing cutoff")
                complete = row["status"] == "MATCHED_SELF_DECLARED"
                if not complete:
                    missing.append(position_id)
                else:
                    total += Decimal(row["total_charge_currency"])
                details.append(dict(position_id=position_id, status=row["status"],
                                    due_rollovers=row["due_rollovers"],
                                    matched_rollovers=row["matched_rollovers"],
                                    missing_rollovers=row["missing_rollovers"],
                                    selected_revisions=row["selected_revisions"],
                                    declared_total_currency=row["total_charge_currency"]))
            snapshots.append(dict(
                cutoff=cutoff,
                status="WITHHELD_INCOMPLETE_DECLARED_FINANCING" if missing else "COMPLETE_SELF_DECLARED_ONLY",
                expected_positions=len(expected),
                matched_positions=len(expected) - len(missing),
                missing_or_unverified_positions=missing,
                total_financing_currency=None if missing else format(total.quantize(Decimal("0.01")), ".2f"),
                positions=details,
            ))
    canonical_versions = sorted(versions, key=lambda r: (r["position_id"], r["rollover_at"], r["revision"], r["receipt_id"]))
    return dict(
        protocol=_PROTOCOL,
        expected_manifest_sha256=digest,
        declaration_sha256=_canonical_sha(dict(manifest_sha256=digest, versions=canonical_versions)),
        expected_positions=len(expected),
        declared_receipt_versions=len(versions),
        snapshots=snapshots,
        source_authenticated=False,
        complete_broker_position_population_verified=False,
        independent_preregistration_verified=False,
        real_execution_costs_verified=False,
        verified_profitability=False,
        may_execute_order=False,
        warning=("A matching declared population digest does not authenticate the broker, "
                 "prove position/rollover completeness, establish prior registration, "
                 "convert currencies, price spreads/slippage, or demonstrate trading profit."),
    )
