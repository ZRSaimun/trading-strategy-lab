"""Offline, outcome-free source-cohort precommitment for M1 exploratory research.

The expected digest must be independently retained *before* evaluating outcomes.
Recomputing it from evaluated receipts is not a valid precommitment.
"""
from __future__ import annotations

import hashlib
import hmac

from app.offline_m1_multi_archive_census import (
    IDENT, POLICY, SHA, _canonical, audit_m1_multi_archive_census,
)

_KEYS = frozenset(("instrument", "provider", "archive_sha256", "bar_manifest_sha256"))
_SCHEMA = "exploratory-m1-cohort-identity-precommit-v1"


def _normalize(entries):
    if not isinstance(entries, (list, tuple)) or not 2 <= len(entries) <= 64:
        raise ValueError("Expected 2..64 pre-outcome archive identities")
    seen_archives, seen_manifests = set(), set()
    normalized = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != _KEYS:
            raise ValueError("Exact pre-outcome archive identity fields required")
        for key in ("instrument", "provider"):
            if not isinstance(entry[key], str) or not IDENT.fullmatch(entry[key]):
                raise ValueError("Invalid pre-outcome source identity")
        for key in ("archive_sha256", "bar_manifest_sha256"):
            if not isinstance(entry[key], str) or not SHA.fullmatch(entry[key]):
                raise ValueError("Invalid pre-outcome SHA-256")
        if (entry["archive_sha256"] in seen_archives
                or entry["bar_manifest_sha256"] in seen_manifests):
            raise ValueError("Duplicate pre-outcome archive or manifest identity")
        seen_archives.add(entry["archive_sha256"])
        seen_manifests.add(entry["bar_manifest_sha256"])
        normalized.append(dict(entry))
    return sorted(normalized, key=lambda e: (
        e["instrument"], e["provider"], e["archive_sha256"], e["bar_manifest_sha256"]
    ))


def prepare_m1_cohort_precommitment(entries):
    """Digest exact source/manifest identities; never accepts performance outcomes.

    The returned digest is only a commitment if independently recorded before
    research results were viewed. It cannot authenticate archive provenance.
    """
    identities = _normalize(entries)
    body = {"schema": _SCHEMA, "policy": POLICY, "archive_identities": identities}
    digest = hashlib.sha256(_canonical(body).encode("ascii")).hexdigest()
    return {
        "schema": _SCHEMA,
        "policy": POLICY,
        "archive_count": len(identities),
        "source_cohort_sha256": digest,
        "research_only": True,
        "trade_authorized": False,
        "protected_holdout": False,
        "source_authenticity_verified": False,
        "warning": "Digest is not independent evidence of registration time, source authenticity, licensing, or holdout status.",
    }


def require_m1_precommitted_cohort(reports, expected_source_cohort_sha256):
    """Fail closed if validated v1 receipts differ from the external cohort digest.

    Reports remain exploratory; no chronology, price-side or execution is proven.
    """
    if (not isinstance(expected_source_cohort_sha256, str)
            or not SHA.fullmatch(expected_source_cohort_sha256)):
        raise ValueError("Independently retained expected cohort SHA-256 required")
    census = audit_m1_multi_archive_census(reports)
    entries = [{
        "instrument": report["source"]["instrument"],
        "provider": report["source"]["provider"],
        "archive_sha256": report["source"]["archive_sha256"],
        "bar_manifest_sha256": report["bar_manifest_sha256"],
    } for report in reports]
    actual = prepare_m1_cohort_precommitment(entries)
    if not hmac.compare_digest(actual["source_cohort_sha256"], expected_source_cohort_sha256):
        raise ValueError("Evaluated archive cohort differs from precommitted identity set")
    return {
        "schema": _SCHEMA,
        "policy": POLICY,
        "archive_count": actual["archive_count"],
        "source_cohort_sha256": actual["source_cohort_sha256"],
        "source_census_sha256": census["research_sha256"],
        "groups": census["groups"],
        "research_only": True,
        "trade_authorized": False,
        "verified_profitability": False,
        "protected_holdout": False,
        "source_authenticity_verified": False,
        "executable_quotes_verified": False,
        "warning": "Caller-supplied expected digest must be independently retained before outcomes; self-hashes cannot prove this. Exploratory only, no executable costs, vendor authentication, verified chronology or trading authorization.",
    }
