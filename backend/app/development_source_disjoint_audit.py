"""Fail-closed, offline *declared* walk-forward source and label-disjointness audit.

This checks metadata, not raw archive bytes or realized labels. A SHA-256 string
is not an independently verified archive, timestamp, or preregistration.
No network, broker access, orders, or trading-performance calculations.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_CCY = re.compile(r"[A-Z]{3}\Z")
_SOURCE = {"provider", "venue", "instrument", "quote_side", "account_alias", "settlement_currency", "utc_convention"}
_MANIFEST = {"source", "archives", "registered_at", "development_end", "validation_start", "holdout_start", "embargo_seconds", "expected_observation_count"}
_ARCHIVE = {"archive_id", "sha256", "first_at", "end_at"}
_OBSERVATION = {"observation_id", "archive_id", "row_sha256", "row_at", "feature_start_at", "decision_at", "label_available_at"}
_FOLD = {"fold_id", "train_start", "train_end", "test_start", "test_end", "train_ids", "test_ids"}
_MAX_TIME = 8640000000


def _exact(value, keys, name):
    if type(value) is not dict or set(value) != keys:
        raise ValueError(f"Invalid exact {name} schema")


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _time(value):
    return type(value) is int and 0 <= value <= _MAX_TIME


def _canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii")).hexdigest()


def audit_development_source_disjointness(manifest, observations, folds):
    """Audit complete declared development observation membership and timing.

    Expanding training may reuse earlier test observations only *after* their
    labels become available and the next fold's embargo is satisfied. Test
    observations cannot appear in more than one test fold. No validation or
    holdout outcomes are accepted, and no claimed seal is authenticated.
    """
    _exact(manifest, _MANIFEST, "manifest")
    source = manifest["source"]
    _exact(source, _SOURCE, "source")
    for key in ("provider", "venue", "instrument", "account_alias"):
        if not _id(source[key]):
            raise ValueError("Invalid source identity")
    if source["quote_side"] not in ("BID", "ASK", "MID") or source["utc_convention"] != "UTC":
        raise ValueError("Unverified quote side or UTC convention")
    if type(source["settlement_currency"]) is not str or not _CCY.fullmatch(source["settlement_currency"]):
        raise ValueError("Invalid source currency")
    if not all(_time(manifest[k]) for k in ("registered_at", "development_end", "validation_start", "holdout_start")):
        raise ValueError("Invalid partition clock")
    if not (manifest["registered_at"] < manifest["development_end"] <= manifest["validation_start"] < manifest["holdout_start"]):
        raise ValueError("Invalid chronological partition boundaries")
    embargo = manifest["embargo_seconds"]
    if type(embargo) is not int or not 1 <= embargo <= 604800:
        raise ValueError("Explicit bounded positive embargo required")
    expected = manifest["expected_observation_count"]
    if type(expected) is not int or not 1 <= expected <= 50000:
        raise ValueError("Invalid declared population count")
    archives = manifest["archives"]
    if type(archives) is not list or not 1 <= len(archives) <= 256:
        raise ValueError("Invalid bounded archive population")
    archive_map, archive_hashes = {}, set()
    for row in archives:
        _exact(row, _ARCHIVE, "archive")
        if (not _id(row["archive_id"]) or row["archive_id"] in archive_map
                or not _sha(row["sha256"]) or row["sha256"] in archive_hashes
                or not _time(row["first_at"]) or not _time(row["end_at"])
                or row["first_at"] >= row["end_at"] or row["end_at"] > manifest["development_end"]):
            raise ValueError("Duplicate, overlapping or invalid archive identity")
        archive_map[row["archive_id"]] = row
        archive_hashes.add(row["sha256"])
    by_time = sorted(archives, key=lambda r: r["first_at"])
    if any(a["end_at"] > b["first_at"] for a, b in zip(by_time, by_time[1:])):
        raise ValueError("Overlapping source archive intervals")

    if type(observations) is not list or len(observations) != expected:
        raise ValueError("Declared observation census is incomplete")
    obs, row_hashes, row_times = {}, set(), set()
    for row in observations:
        _exact(row, _OBSERVATION, "observation (no outcomes permitted)")
        key = row["observation_id"]
        archive = archive_map.get(row["archive_id"])
        if not _id(key) or key in obs or archive is None or not _sha(row["row_sha256"]):
            raise ValueError("Invalid or duplicate observation identity")
        if not all(_time(row[k]) for k in ("row_at", "feature_start_at", "decision_at", "label_available_at")):
            raise ValueError("Invalid observation clock")
        if not (archive["first_at"] <= row["row_at"] < archive["end_at"]
                and row["feature_start_at"] <= row["row_at"] <= row["decision_at"]
                < row["label_available_at"] <= manifest["development_end"]):
            raise ValueError("Noncausal, cross-archive or post-development observation")
        # One raw row/decision per declared observation. This is conservative:
        # legitimate duplicate source rows must be independently reconciled.
        if row["row_sha256"] in row_hashes or row["row_at"] in row_times:
            raise ValueError("Reused raw row or cross-archive timestamp ambiguity")
        obs[key] = row
        row_hashes.add(row["row_sha256"])
        row_times.add(row["row_at"])

    if type(folds) is not list or not 2 <= len(folds) <= 32:
        raise ValueError("Require 2..32 declared chronological folds")
    seen_fold_ids, seen_test_ids, used_ids, fold_reports, years = set(), set(), set(), [], set()
    previous_test_end, previous_train_end = -1, -1
    first_train_start = None
    for fold in folds:
        _exact(fold, _FOLD, "fold")
        if not _id(fold["fold_id"]) or fold["fold_id"] in seen_fold_ids:
            raise ValueError("Duplicate or invalid fold ID")
        seen_fold_ids.add(fold["fold_id"])
        if not all(_time(fold[k]) for k in ("train_start", "train_end", "test_start", "test_end")):
            raise ValueError("Invalid fold clocks")
        ts, te, vs, ve = (fold[k] for k in ("train_start", "train_end", "test_start", "test_end"))
        if not (ts < te <= vs < ve <= manifest["development_end"] and te + embargo <= vs):
            raise ValueError("Overlapping, non-embargoed or post-development fold")
        if first_train_start is None:
            first_train_start = ts
            if manifest["registered_at"] >= vs:
                raise ValueError("Study registration was not before first test")
        if ts != first_train_start or te <= previous_train_end or vs < previous_test_end:
            raise ValueError("Nonexpanding training or repeated test window")
        previous_train_end, previous_test_end = te, ve
        train_ids, test_ids = fold["train_ids"], fold["test_ids"]
        if (type(train_ids) is not list or type(test_ids) is not list
                or not train_ids or not test_ids or len(train_ids) > expected or len(test_ids) > expected
                or any(not _id(x) for x in train_ids + test_ids)
                or len(set(train_ids)) != len(train_ids) or len(set(test_ids)) != len(test_ids)
                or set(train_ids) & set(test_ids)):
            raise ValueError("Invalid, repeated or overlapping fold membership")
        for key in train_ids:
            row = obs.get(key)
            if row is None or not (ts <= row["decision_at"] < te and row["feature_start_at"] >= ts
                                   and row["label_available_at"] + embargo <= vs):
                raise ValueError("Training observation leaks into test or embargo")
        for key in test_ids:
            row = obs.get(key)
            if row is None or key in seen_test_ids or not (vs <= row["decision_at"] < ve
                    and row["feature_start_at"] >= ts):
                raise ValueError("Reused, unknown or out-of-window test observation")
            years.add(datetime.fromtimestamp(row["decision_at"], timezone.utc).year)
            seen_test_ids.add(key)
        # A declared population is not a complete census if the caller may
        # silently omit an eligible losing observation from a fold. Verify
        # the entire eligible membership, not only the supplied ID subset.
        eligible_train = {key for key, row in obs.items()
                          if ts <= row["decision_at"] < te
                          and row["feature_start_at"] >= ts
                          and row["label_available_at"] + embargo <= vs}
        eligible_test = {key for key, row in obs.items()
                         if vs <= row["decision_at"] < ve
                         and row["feature_start_at"] >= ts}
        if set(train_ids) != eligible_train or set(test_ids) != eligible_test:
            raise ValueError("Selective fold membership or omitted eligible observation")
        used_ids.update(train_ids)
        used_ids.update(test_ids)
        fold_reports.append({"fold_id": fold["fold_id"], "training_count": len(train_ids),
                             "testing_count": len(test_ids), "test_years": sorted({datetime.fromtimestamp(obs[k]["decision_at"], timezone.utc).year for k in test_ids})})
    if used_ids != set(obs):
        raise ValueError("Incomplete fold observation census: undeclared exclusions")
    canonical = {"manifest": dict(manifest, archives=sorted(archives, key=lambda r: r["archive_id"])),
                 "observations": sorted(observations, key=lambda r: r["observation_id"]),
                 "folds": [dict(f, train_ids=sorted(f["train_ids"]), test_ids=sorted(f["test_ids"])) for f in folds]}
    return {"protocol": "declared-development-source-disjoint-v1",
            "status": "DECLARED_TIMING_ONLY" if len(years) >= 3 and len(folds) >= 3 else "WITHHELD_INSUFFICIENT_MULTIYEAR",
            "declaration_sha256": _canonical_hash(canonical), "folds": fold_reports,
            "development_observations": len(obs), "unique_test_observations": len(seen_test_ids),
            "test_years": sorted(years), "source_authenticated": False,
            "independent_preregistration_verified": False, "untouched_holdout_verified": False,
            "actual_costs_verified": False, "verified_profitability": False,
            "may_execute_order": False,
            "warning": "Self-declared archive and row digests, clocks, membership and registration are not independent evidence; no validation/holdout outcomes, costs or broker fills were read."}
