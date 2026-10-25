"""Offline, fail-closed candidate-selection census for development walk-forward folds.

All clocks, identities, scores and registration receipts are caller-declared.
This module neither authenticates a precommitment nor reads holdout outcomes.
"""
from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation

from app.walkforward_fold_audit import audit_development_walkforward

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SCORE = re.compile(r"-?(?:0|[1-9][0-9]{0,8})(?:\.[0-9]{1,6})?\Z")
_CANDIDATE_FIELDS = {"id", "configSha256"}
_REGISTRATION_FIELDS = {"registeredAt", "manifestSha256"}
_TRIAL_FIELDS = {"candidateId", "foldId", "configSha256", "sourceSha256", "testSetSha256", "score", "observedAt"}
_SELECTION_FIELDS = {"candidateId", "selectedConfigSha256", "selectedAt", "candidateCount", "trialCount", "policy"}
_POLICY = "max_equal_fold_mean_tie_lexicographic_id"
_MAX_CANDIDATES = 64


def _exact(record, keys, kind):
    if type(record) is not dict or set(record) != keys:
        raise ValueError(f"{kind}: exact schema required")


def _time(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def _sha(value):
    return type(value) is str and _SHA.fullmatch(value) is not None


def _id(value):
    return type(value) is str and _ID.fullmatch(value) is not None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True).encode("ascii")).hexdigest()


def _score(value):
    if type(value) is not str or _SCORE.fullmatch(value) is None:
        raise ValueError("Score must be a bounded, finite, exact decimal string")
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Invalid decimal score") from exc
    if abs(result) > 1_000_000:
        raise ValueError("Score outside declared research bound")
    return result


def _prepare(archives, observations, protocol, folds, candidates):
    # Never accept an unverified caller-supplied audit result as a shortcut.
    audit = audit_development_walkforward(archives, observations, protocol, folds)
    if (type(candidates) is not list or not 1 <= len(candidates) <= _MAX_CANDIDATES or
            not audit["folds"] or any(f["status"] != "TIMING_ONLY" for f in audit["folds"])):
        raise ValueError("Insufficient folds or invalid candidate population")
    ids, hashes = set(), set()
    for c in candidates:
        _exact(c, _CANDIDATE_FIELDS, "Candidate")
        if (not _id(c["id"]) or not _sha(c["configSha256"]) or
                c["id"] in ids or c["configSha256"] in hashes):
            raise ValueError("Invalid or duplicate candidate identity/configuration")
        ids.add(c["id"])
        hashes.add(c["configSha256"])
    source_sha = _hash({"source": audit["source"], "archiveLineage": audit["archiveLineage"]})
    fold_hashes = {f["id"]: _hash(sorted(f["testIds"])) for f in audit["folds"]}
    frozen = {"engine": audit["engine"], "sourceSha256": source_sha,
              "protocol": audit["protocol"],
              "folds": [{"id": f["id"], "bounds": f["bounds"],
                         "trainIds": sorted(f["trainIds"]), "testIds": sorted(f["testIds"]),
                         "excludedCounts": f["excludedCounts"]} for f in audit["folds"]],
              "candidates": sorted(candidates, key=lambda c: c["id"])}
    return audit, source_sha, fold_hashes, _hash(frozen)


def candidate_registration_digest(archives, observations, protocol, folds, candidates):
    """Deterministic *untrusted* manifest digest to anchor externally before testing."""
    return _prepare(archives, observations, protocol, folds, candidates)[3]


def audit_development_candidate_census(archives, observations, protocol, folds,
                                       candidates, registration, trials, selection):
    """Check a declared full candidate x fold census without touching holdouts.

    Scores are supplied, not computed or verified. A complete declared census
    cannot prove omitted experiments do not exist or prevent retrospective edits.
    """
    audit, source_sha, fold_hashes, digest = _prepare(
        archives, observations, protocol, folds, candidates)
    _exact(registration, _REGISTRATION_FIELDS, "Registration")
    _exact(selection, _SELECTION_FIELDS, "Selection")
    earliest_test = min(f["bounds"]["testStart"] for f in audit["folds"])
    dev = protocol["developmentEnd"]
    if (not _time(registration["registeredAt"]) or
            registration["registeredAt"] >= earliest_test or
            not _sha(registration["manifestSha256"]) or
            registration["manifestSha256"] != digest):
        raise ValueError("Registration must match the frozen development census before testing")
    if (type(trials) is not list or len(trials) != len(candidates) * len(folds) or
            len(trials) > _MAX_CANDIDATES * 100):
        raise ValueError("Incomplete, excessive or malformed candidate-fold census")
    if (not _id(selection["candidateId"]) or not _sha(selection["selectedConfigSha256"]) or
            not _time(selection["selectedAt"]) or selection["selectedAt"] >= dev or
            type(selection["candidateCount"]) is not int or
            selection["candidateCount"] != len(candidates) or
            type(selection["trialCount"]) is not int or
            selection["trialCount"] != len(trials) or
            selection["policy"] != _POLICY):
        raise ValueError("Selection violates frozen policy, count or development cutoff")
    by_candidate = {c["id"]: c for c in candidates}
    by_fold = {f["id"]: f for f in audit["folds"]}
    seen, scores, latest_observed = set(), {c["id"]: [] for c in candidates}, -1
    for trial in trials:
        _exact(trial, _TRIAL_FIELDS, "Trial")
        cid, fid = trial["candidateId"], trial["foldId"]
        if type(cid) is not str or type(fid) is not str or cid not in by_candidate or fid not in by_fold:
            raise ValueError("Undeclared candidate or fold trial")
        key = (cid, fid)
        if key in seen:
            raise ValueError("Duplicate candidate-fold trial")
        seen.add(key)
        fold = by_fold[fid]
        if (trial["configSha256"] != by_candidate[cid]["configSha256"] or
                trial["sourceSha256"] != source_sha or
                trial["testSetSha256"] != fold_hashes[fid] or
                not _time(trial["observedAt"]) or
                not fold["bounds"]["testEnd"] < trial["observedAt"] < dev or
                trial["observedAt"] < registration["registeredAt"]):
            raise ValueError("Trial has source, configuration, test-set or time leakage")
        scores[cid].append(_score(trial["score"]))
        latest_observed = max(latest_observed, trial["observedAt"])
    if len(seen) != len(candidates) * len(folds) or selection["selectedAt"] < latest_observed:
        raise ValueError("Incomplete census or selection before all outcomes were observed")
    means = {cid: sum(vals, Decimal(0)) / Decimal(len(folds)) for cid, vals in scores.items()}
    winner = sorted(means, key=lambda cid: (-means[cid], cid))[0]
    if (selection["candidateId"] != winner or
            selection["selectedConfigSha256"] != by_candidate[winner]["configSha256"]):
        raise ValueError("Selection differs from declared deterministic ranking")
    return {"engine": "development-candidate-census-v1", "status": "DECLARED_ONLY",
            "registrationManifestSha256": digest, "sourceSha256": source_sha,
            "candidateCount": len(candidates), "foldCount": len(folds),
            "trialCount": len(trials), "selectedCandidateId": winner,
            "selectedConfigSha256": by_candidate[winner]["configSha256"],
            "declaredMeanScores": {cid: str(means[cid]) for cid in sorted(means)},
            "multipleTestingCandidateCount": len(candidates),
            "sourceAuthenticated": False, "preregistrationExternallyVerified": False,
            "candidateCompletenessExternallyVerified": False,
            "validationHoldoutAccess": False, "profitabilityEstablished": False,
            "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False,
            "warning": "Scores, clocks and registration are caller claims; external timestamped preregistration, full experiment census, untouched holdout, costs, uncertainty and authentic source data remain unverified."}
