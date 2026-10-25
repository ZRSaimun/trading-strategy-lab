"""Offline, revision-aware point-in-time feature lineage audit.

This checks caller-declared clocks and SHA identifiers, NOT vendor provenance,
actual feature values, model causality, historical availability, or trading safety.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
import hashlib
import json
import re

_PROTOCOL = "asof-feature-vintage-manifest-v1"
_REPORT = "asof-feature-vintage-audit-v1"
_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_EPOCH = 8640000000
_MAX_AGE = 315360000


def _exact(obj, keys, label):
    if not isinstance(obj, dict) or set(obj) != set(keys):
        raise ValueError(f"{label} requires exact fields")


def _id(value):
    return isinstance(value, str) and bool(_ID.fullmatch(value))


def _sha(value):
    return isinstance(value, str) and bool(_SHA.fullmatch(value))


def _clock(value):
    return type(value) is int and 0 <= value <= _MAX_EPOCH


def _validate(manifest):
    _exact(manifest, ("protocol", "decision_source", "decisions", "series", "vintages"), "Manifest")
    if manifest["protocol"] != _PROTOCOL:
        raise ValueError("Unknown manifest protocol")
    source = manifest["decision_source"]
    _exact(source, ("provider", "instrument", "venue", "archive_sha256", "price_side"), "Decision source")
    if not all(_id(source[k]) for k in ("provider", "instrument", "venue")) or not _sha(source["archive_sha256"]):
        raise ValueError("Invalid decision source identity")
    if source["price_side"] not in ("BID", "ASK", "MID", "TRADE"):
        raise ValueError("Invalid decision price side")

    decisions, series, vintages = (manifest[k] for k in ("decisions", "series", "vintages"))
    if not isinstance(decisions, list) or not 1 <= len(decisions) <= 10000:
        raise ValueError("Invalid bounded decision population")
    if not isinstance(series, list) or not 1 <= len(series) <= 64:
        raise ValueError("Invalid bounded series population")
    if not isinstance(vintages, list) or len(vintages) > 50000:
        raise ValueError("Invalid bounded vintage population")
    if len(decisions) * len(series) > 100000:
        raise ValueError("Decision-series cross-product exceeds limit")

    ids = set()
    for decision in decisions:
        _exact(decision, ("decision_id", "at"), "Decision")
        if not _id(decision["decision_id"]) or decision["decision_id"] in ids:
            raise ValueError("Invalid or duplicate decision ID")
        ids.add(decision["decision_id"])
        if not _clock(decision["at"]):
            raise ValueError("Invalid decision UTC clock")

    series_ids = set()
    for item in series:
        _exact(item, ("series_id", "provider", "instrument", "venue", "archive_sha256", "max_age_seconds"), "Series")
        if not _id(item["series_id"]) or item["series_id"] in series_ids:
            raise ValueError("Invalid or duplicate series ID")
        series_ids.add(item["series_id"])
        if not all(_id(item[k]) for k in ("provider", "instrument", "venue")) or not _sha(item["archive_sha256"]):
            raise ValueError("Invalid feature source identity")
        if type(item["max_age_seconds"]) is not int or not 0 <= item["max_age_seconds"] <= _MAX_AGE:
            raise ValueError("Invalid feature max age")

    grouped = defaultdict(list)
    for item in vintages:
        _exact(item, ("series_id", "observation_at", "available_at", "revision", "value_sha256"), "Vintage")
        if not _id(item["series_id"]) or item["series_id"] not in series_ids:
            raise ValueError("Unknown vintage series identity")
        if not _clock(item["observation_at"]) or not _clock(item["available_at"]):
            raise ValueError("Invalid vintage UTC clock")
        if item["available_at"] < item["observation_at"]:
            raise ValueError("Vintage published before observation")
        if type(item["revision"]) is not int or not 0 <= item["revision"] <= 10000:
            raise ValueError("Invalid revision number")
        if not _sha(item["value_sha256"]):
            raise ValueError("Invalid feature value SHA-256")
        grouped[(item["series_id"], item["observation_at"])].append(item)
    for group in grouped.values():
        group.sort(key=lambda x: x["revision"])
        for revision, item in enumerate(group):
            if item["revision"] != revision:
                raise ValueError("Missing or duplicate vintage revision")
            if revision and item["available_at"] <= group[revision - 1]["available_at"]:
                raise ValueError("Revisions must have strictly increasing availability")
    return grouped


def fingerprint_feature_vintages(manifest):
    """Order-independent SHA receipt for supplied metadata, not preregistration."""
    _validate(manifest)
    canonical = dict(
        protocol=_PROTOCOL, decision_source=manifest["decision_source"],
        decisions=sorted(manifest["decisions"], key=lambda x: x["decision_id"]),
        series=sorted(manifest["series"], key=lambda x: x["series_id"]),
        vintages=sorted(manifest["vintages"], key=lambda x: (x["series_id"], x["observation_at"], x["revision"])),
    )
    raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def audit_asof_feature_vintages(manifest, expected_manifest_sha256):
    """Select latest *available* observation, then its latest available revision.

    Never select by latest observation alone: a newly observed feature can
    remain unpublished at a decision, while an older vintage is usable.
    """
    if not _sha(expected_manifest_sha256):
        raise ValueError("Expected manifest SHA-256 required")
    digest = fingerprint_feature_vintages(manifest)
    if digest != expected_manifest_sha256:
        raise ValueError("Frozen feature manifest SHA-256 mismatch")
    grouped = _validate(manifest)
    index = defaultdict(list)
    for (series_id, observed), group in grouped.items():
        for item in group:
            index[series_id].append(item)
    # Published clock is primary; ties are resolved by observation then revision.
    by_series = {}
    for series_id, items in index.items():
        ordered = sorted(items, key=lambda x: (x["available_at"], x["observation_at"], x["revision"]))
        best = []
        current = None
        for item in ordered:
            if current is None or (item["observation_at"], item["revision"]) > (current["observation_at"], current["revision"]):
                current = item
            best.append(current)
        by_series[series_id] = ([x["available_at"] for x in ordered], best)
    results = []
    counts = dict(SELECTED=0, MISSING_ASOF=0, STALE_ASOF=0)
    for decision in sorted(manifest["decisions"], key=lambda x: (x["at"], x["decision_id"])):
        for series in sorted(manifest["series"], key=lambda x: x["series_id"]):
            series_id = series["series_id"]
            clocks, best = by_series.get(series_id, ([], []))
            upto = bisect_right(clocks, decision["at"])
            chosen = best[upto - 1] if upto else None
            row = dict(decision_id=decision["decision_id"], decision_at=decision["at"], series_id=series_id)
            if chosen is None:
                row["status"] = "MISSING_ASOF"
            elif decision["at"] - chosen["observation_at"] > series["max_age_seconds"]:
                row["status"] = "STALE_ASOF"
            else:
                row.update(status="SELECTED", observation_at=chosen["observation_at"],
                           available_at=chosen["available_at"], revision=chosen["revision"],
                           value_sha256=chosen["value_sha256"])
            counts[row["status"]] += 1
            results.append(row)
    return dict(
        protocol=_REPORT, status=("COMPLETE_DECLARED_ONLY" if counts["SELECTED"] == len(results)
                                  else "WITHHELD_MISSING_OR_STALE"),
        manifest_sha256=digest, decision_source=dict(manifest["decision_source"]),
        decisions=len(manifest["decisions"]), required_series=len(manifest["series"]),
        declared_vintages=len(manifest["vintages"]), counts=counts, selections=results,
        independent_source_authentication=False, independent_release_clock_verification=False,
        independent_preregistration_verified=False, complete_vendor_revision_history_verified=False,
        no_future_vintage_selected=True, may_execute_order=False, verified_profitability=False,
        warning=("Only declared release clocks and hashes were checked. Missing historical revisions, "
                 "late vendor corrections, source licensing, actual values and causal market data "
                 "cannot be independently verified. Do not use this report as an execution gate "
                 "or evidence of a profitable strategy."),
    )
