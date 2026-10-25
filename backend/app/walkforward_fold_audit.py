"""Offline, metadata-only walk-forward fold audit; never reads outcomes or orders.

Caller-declared archive identities and clocks are NOT authenticated evidence.
This is a conservative development-only fold gate, not a backtester.
"""
from __future__ import annotations

import re
from collections import Counter

SHA = re.compile(r"[0-9a-f]{64}\Z")
YEAR = 365 * 86400
MAX_ARCHIVES, MAX_OBSERVATIONS, MAX_FOLDS = 1000, 50000, 100
ARCHIVE_FIELDS = {"id", "provider", "instrument", "venue", "priceSide", "utcConvention", "archiveSha256", "start", "end"}
OBS_FIELDS = {"id", "archiveId", "featureStart", "decisionAt", "labelAvailableAt"}
PROTOCOL_FIELDS = {"developmentEnd", "validationEnd", "holdoutEnd", "embargoSeconds", "strategyVersion", "configSha256"}
FOLD_FIELDS = {"id", "trainStart", "trainEnd", "testStart", "testEnd"}


def _record(value, fields, name):
    if type(value) is not dict or set(value) != fields:
        raise ValueError(f"{name}: exact metadata fields required; no outcomes or extra fields")


def _time(value):
    return type(value) is int and 0 <= value <= 9007199254740991


def _name(value):
    return type(value) is str and 0 < len(value) <= 200 and value.strip() == value


def _digest(value):
    return type(value) is str and SHA.fullmatch(value) is not None


def audit_development_walkforward(archives: list[dict], observations: list[dict],
                                  protocol: dict, folds: list[dict]) -> dict:
    """Fail closed on source drift, unavailable labels and noncausal folds.

    All fold tests must end in development, leaving validation/holdout untested.
    Label cutoffs are exclusive even when embargo is zero. Observations are
    *timing metadata only*, never P&L, candles, prices or strategy outcomes.
    """
    if (type(archives) is not list or not 1 <= len(archives) <= MAX_ARCHIVES or
            type(observations) is not list or len(observations) > MAX_OBSERVATIONS or
            type(folds) is not list or not 1 <= len(folds) <= MAX_FOLDS):
        raise ValueError("Invalid or unbounded archive, observation or fold population")
    _record(protocol, PROTOCOL_FIELDS, "Protocol")
    dev, val, hold, embargo = (protocol[k] for k in ("developmentEnd", "validationEnd", "holdoutEnd", "embargoSeconds"))
    if (not all(_time(v) for v in (dev, val, hold, embargo)) or
            not dev < val < hold or embargo > 30 * 86400 or
            not _name(protocol["strategyVersion"]) or not _digest(protocol["configSha256"])):
        raise ValueError("Invalid frozen protocol, embargo or chronological boundaries")
    source = None
    seen_ids, seen_digests = set(), set()
    by_id = {}
    lineage = []
    for a in archives:
        _record(a, ARCHIVE_FIELDS, "Archive")
        if (not all(_name(a[k]) for k in ("id", "provider", "instrument", "venue")) or
                not _digest(a["archiveSha256"]) or
                not _time(a["start"]) or not _time(a["end"]) or a["start"] >= a["end"] or
                a["priceSide"] not in ("bid", "ask", "mid", "bid_ask") or a["utcConvention"] != "UTC" or
                a["id"] in seen_ids or a["archiveSha256"] in seen_digests):
            raise ValueError("Invalid, duplicate or unverified archive identity")
        identity = tuple(a[k] for k in ("provider", "instrument", "venue", "priceSide", "utcConvention"))
        if source is not None and source != identity:
            raise ValueError("Mixed source family, instrument, venue or price side")
        source = identity
        seen_ids.add(a["id"])
        seen_digests.add(a["archiveSha256"])
        by_id[a["id"]] = a
        lineage.append(a)
    lineage.sort(key=lambda a: (a["start"], a["id"]))
    gaps = 0
    for earlier, later in zip(lineage, lineage[1:]):
        if later["start"] < earlier["end"]:
            raise ValueError("Overlapping source archives")
        gaps += int(later["start"] > earlier["end"])
    if dev - lineage[0]["start"] < 2 * YEAR or lineage[-1]["end"] < hold:
        raise ValueError("At least two elapsed development years and declared holdout span required")
    seen_obs = set()
    for o in observations:
        _record(o, OBS_FIELDS, "Observation")
        a = by_id.get(o["archiveId"]) if type(o["archiveId"]) is str else None
        if (not _name(o["id"]) or o["id"] in seen_obs or a is None or
                not all(_time(o[k]) for k in ("featureStart", "decisionAt", "labelAvailableAt")) or
                not a["start"] <= o["featureStart"] <= o["decisionAt"] <= o["labelAvailableAt"] < a["end"]):
            raise ValueError("Duplicate, cross-archive, noncausal or malformed observation")
        seen_obs.add(o["id"])
    seen_folds, prior_test_end = set(), -1
    results = []
    for fold in folds:
        _record(fold, FOLD_FIELDS, "Fold")
        train_start, train_end, test_start, test_end = (fold[k] for k in ("trainStart", "trainEnd", "testStart", "testEnd"))
        if (not _name(fold["id"]) or fold["id"] in seen_folds or
                not all(_time(t) for t in (train_start, train_end, test_start, test_end)) or
                not lineage[0]["start"] <= train_start < train_end <= test_start < test_end <= dev or
                test_start - train_end < embargo or test_start < prior_test_end):
            raise ValueError("Fold overlaps another test, accesses validation/holdout or violates embargo")
        seen_folds.add(fold["id"])
        prior_test_end = test_end
        train, test = [], []
        excluded = Counter()
        for o in observations:
            decision, feature, label = o["decisionAt"], o["featureStart"], o["labelAvailableAt"]
            if train_start <= decision < train_end:
                if feature < train_start:
                    excluded["TRAIN_FEATURE_CROSSES_START"] += 1
                elif label >= train_end:
                    excluded["TRAIN_LABEL_UNAVAILABLE"] += 1
                else:
                    train.append(o["id"])
            elif test_start <= decision < test_end:
                if feature < test_start:
                    excluded["TEST_FEATURE_CROSSES_START"] += 1
                elif label >= test_end or label > test_end - embargo:
                    excluded["TEST_LABEL_UNAVAILABLE_OR_EMBARGO"] += 1
                else:
                    test.append(o["id"])
        results.append({"id": fold["id"], "trainIds": train, "testIds": test,
                        "excludedCounts": dict(sorted(excluded.items())),
                        "status": "TIMING_ONLY" if train and test else "INSUFFICIENT_TIMING_OBSERVATIONS"})
    return {"engine": "development-walkforward-timing-v1", "source": dict(zip(
        ("provider", "instrument", "venue", "priceSide", "utcConvention"), source)),
            "strategyVersion": protocol["strategyVersion"], "configSha256": protocol["configSha256"],
            "archiveCount": len(archives), "declaredArchiveGaps": gaps,
            "observationCount": len(observations), "folds": results,
            "validationHoldoutAccess": False, "mayExecuteOrder": False,
            "warning": "Declared metadata only: no outcome inspection, source authentication, market-session completeness, trusted preregistration, executable CFD costs, statistical significance or profitable edge. All validation and holdout periods remain outside fold tests."}
