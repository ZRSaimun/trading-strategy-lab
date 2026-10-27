"""Offline, declared-only holdout release gate; never authorizes brokerage orders.

A caller-supplied timestamp, digest or anchor is NOT independently authenticated.
A stateless function cannot enforce a single evaluation across executions.
"""
from __future__ import annotations

from decimal import Decimal, localcontext
import hashlib
import json
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CCY = re.compile(r"[A-Z]{3}\Z")
_CASH = re.compile(r"-?(?:0|[1-9][0-9]{0,9})(?:\.[0-9]{1,4})?\Z")
_SOURCE = {"provider", "venue", "instrument", "quote_side", "account_alias",
           "settlement_currency", "utc_convention", "archive_sha256"}
_MANIFEST = {"study_id", "source", "candidate_id", "candidate_config_sha256",
             "selection_evidence_sha256", "validation_end_at_utc", "selected_at_utc",
             "registered_at_utc", "holdout_start_at_utc", "holdout_end_at_utc",
             "embargo_seconds", "expected_holdout_count", "holdout_census_sha256"}
_CENSUS = {"observation_id", "row_sha256", "source_sha256", "decision_at_utc",
           "label_available_at_utc"}
_OUTCOME = _CENSUS | {"observed_at_utc", "gross_cash", "spread_cash",
                      "slippage_cash", "commission_cash", "financing_cash", "fx_cash",
                      "receipt_sha256"}
_ANCHOR = {"manifest_sha256", "anchored_at_utc", "anchor_reference",
           "external_record_sha256"}
_MAX_TIME = 8_640_000_000
_MAX_ROWS = 10000
_CHARGES = ("spread_cash", "slippage_cash", "commission_cash", "fx_cash")


def _exact(obj, keys, name):
    if type(obj) is not dict or set(obj) != keys:
        raise ValueError(f"Invalid exact {name} schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _time(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _hash(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _money(value, nonnegative=False):
    if type(value) is not str or _CASH.fullmatch(value) is None:
        raise ValueError("Invalid exact-decimal cash")
    amount = Decimal(value)
    if (amount == 0 and value.startswith("-")) or (nonnegative and amount < 0):
        raise ValueError("Invalid cash sign")
    return amount


def _validate_manifest(manifest):
    _exact(manifest, _MANIFEST, "manifest (no outcomes permitted)")
    source = manifest["source"]
    _exact(source, _SOURCE, "source")
    if not all(_id(source[k]) for k in ("provider", "venue", "instrument", "account_alias")):
        raise ValueError("Invalid source identity")
    if (source["quote_side"] not in ("BID", "ASK", "MID") or
            source["utc_convention"] != "UTC" or
            type(source["settlement_currency"]) is not str or
            _CCY.fullmatch(source["settlement_currency"]) is None or
            not _sha(source["archive_sha256"])):
        raise ValueError("Invalid source convention, currency or archive")
    if not _id(manifest["study_id"]) or not _id(manifest["candidate_id"]):
        raise ValueError("Invalid study/candidate identity")
    if not all(_sha(manifest[k]) for k in ("candidate_config_sha256",
                                              "selection_evidence_sha256",
                                              "holdout_census_sha256")):
        raise ValueError("Invalid manifest evidence digest")
    clocks = ("validation_end_at_utc", "selected_at_utc", "registered_at_utc",
              "holdout_start_at_utc", "holdout_end_at_utc")
    if not all(_time(manifest[k]) for k in clocks):
        raise ValueError("Invalid manifest clocks")
    if (type(manifest["embargo_seconds"]) is not int or
            not 1 <= manifest["embargo_seconds"] <= 2_592_000 or
            not (manifest["validation_end_at_utc"] + manifest["embargo_seconds"] <=
                 manifest["selected_at_utc"] <= manifest["registered_at_utc"] <
                 manifest["holdout_start_at_utc"] < manifest["holdout_end_at_utc"])):
        raise ValueError("Invalid selection/registration/embargo/holdout chronology")
    count = manifest["expected_holdout_count"]
    if type(count) is not int or not 1 <= count <= _MAX_ROWS:
        raise ValueError("Invalid bounded holdout population")


def _validate_census(manifest, census):
    if type(census) is not list or len(census) != manifest["expected_holdout_count"]:
        raise ValueError("Missing or extra declared holdout observation")
    ids, row_hashes, decisions, previous = set(), set(), set(), -1
    for row in census:
        _exact(row, _CENSUS, "holdout census (no outcomes permitted)")
        if (not _id(row["observation_id"]) or row["observation_id"] in ids or
                not _sha(row["row_sha256"]) or row["row_sha256"] in row_hashes or
                row["source_sha256"] != manifest["source"]["archive_sha256"] or
                not _time(row["decision_at_utc"]) or
                not _time(row["label_available_at_utc"]) or
                not (manifest["holdout_start_at_utc"] <= row["decision_at_utc"] <
                     manifest["holdout_end_at_utc"]) or
                not row["decision_at_utc"] < row["label_available_at_utc"] or
                row["decision_at_utc"] in decisions or
                row["decision_at_utc"] <= previous):
            raise ValueError("Duplicate, cross-source or noncausal holdout observation")
        previous = row["decision_at_utc"]
        ids.add(row["observation_id"])
        row_hashes.add(row["row_sha256"])
        decisions.add(row["decision_at_utc"])
    if _hash(census) != manifest["holdout_census_sha256"]:
        raise ValueError("Declared holdout population differs from manifest commitment")


def prepare_declared_holdout_census_sha256(census):
    """Produce a caller-declared digest, NOT a preregistration or archive proof."""
    if type(census) is not list or not 1 <= len(census) <= _MAX_ROWS:
        raise ValueError("Invalid census population")
    for row in census:
        _exact(row, _CENSUS, "census")
    return _hash(census)


def prepare_declared_holdout_manifest_sha256(manifest):
    """Produce a digest to preserve in an independently trusted registry."""
    _validate_manifest(manifest)
    return _hash(manifest)


def audit_declared_holdout_release(manifest, census, anchor, outcomes, release_at_utc):
    """Audit one declared candidate's complete, point-in-time holdout release.

    Only external immutable registry controls can substantiate an actual
    preregistration, prevent repeated peeks or establish holdout untouchedness.
    """
    _validate_manifest(manifest)
    _validate_census(manifest, census)
    _exact(anchor, _ANCHOR, "external anchor declaration")
    if (anchor["manifest_sha256"] != _hash(manifest) or
            not _id(anchor["anchor_reference"]) or
            not _sha(anchor["external_record_sha256"]) or
            not _time(anchor["anchored_at_utc"]) or
            not (manifest["registered_at_utc"] <= anchor["anchored_at_utc"] <
                 manifest["holdout_start_at_utc"])):
        raise ValueError("Missing, late or mismatched declared registration anchor")
    if (not _time(release_at_utc) or
            release_at_utc < manifest["holdout_end_at_utc"] or
            release_at_utc < anchor["anchored_at_utc"]):
        raise ValueError("Holdout release is premature")
    if type(outcomes) is not list or len(outcomes) != len(census):
        raise ValueError("Incomplete holdout outcome census")
    by_id = {r["observation_id"]: r for r in census}
    seen, receipts, parsed = set(), set(), {}
    with localcontext() as ctx:
        ctx.prec = 80
        for row in outcomes:
            _exact(row, _OUTCOME, "holdout outcome")
            key = row["observation_id"]
            original = by_id.get(key) if _id(key) else None
            if original is None or key in seen or any(row[k] != original[k] for k in _CENSUS):
                raise ValueError("Missing, duplicated or altered holdout membership")
            if (not _time(row["observed_at_utc"]) or
                    not original["label_available_at_utc"] <= row["observed_at_utc"] <= release_at_utc or
                    not _sha(row["receipt_sha256"]) or row["receipt_sha256"] in receipts):
                raise ValueError("Unobserved outcome or reused receipt")
            gross = _money(row["gross_cash"])
            costs = sum((_money(row[k], nonnegative=True) for k in _CHARGES), Decimal(0))
            financing = _money(row["financing_cash"])
            parsed[key] = gross - costs - financing
            seen.add(key)
            receipts.add(row["receipt_sha256"])
        if seen != set(by_id):
            raise ValueError("Incomplete holdout outcome population")
        total = running = peak = drawdown = Decimal(0)
        worst = None
        for item in census:
            net = parsed[item["observation_id"]]
            total += net
            running += net
            peak = max(peak, running)
            drawdown = max(drawdown, peak - running)
            worst = net if worst is None else min(worst, net)
        # A withheld holdout must not reveal the result it purports to withhold.
        # Otherwise repeated small-sample probes can tune candidates on holdout P&L.
        sufficient = len(census) >= 30
        return {
            "protocol": "declared-holdout-release-gate-v1",
            "status": "DECLARED_EVALUATION_ONLY" if sufficient else
                      "WITHHELD_INSUFFICIENT_HOLDOUT",
            "study_id": manifest["study_id"],
            "candidate_id": manifest["candidate_id"],
            "manifest_sha256": _hash(manifest),
            "holdout_census_sha256": _hash(census),
            "outcome_receipts_sha256": (
                _hash(sorted(outcomes, key=lambda x: x["observation_id"])) if sufficient else None
            ),
            "observation_count": len(census),
            "outcome_metrics_withheld": not sufficient,
            "net_cash": format(total, ".4f") if sufficient else None,
            "worst_observation_net_cash": format(worst, ".4f") if sufficient else None,
            "max_observation_end_drawdown_cash": (
                format(drawdown, ".4f") if sufficient else None
            ),
            "anchor_independently_authenticated": False,
            "source_bytes_independently_authenticated": False,
            "one_time_release_enforced": False,
            "holdout_untouched_independently_verified": False,
            "broker_costs_verified": False,
            "profitable_edge_verified": False,
            "may_execute_demo_order": False,
            "may_execute_real_order": False,
            "warning": "All clocks, source digests, receipts and the anchor are caller-declared. "
                       "An external immutable registry is needed to prove precommitment and one-time release. "
                       "Observation-end drawdown omits intraperiod risk. No broker fills are verified. "
                       "For fewer than 30 observations, outcome-dependent fields are withheld."
        }
