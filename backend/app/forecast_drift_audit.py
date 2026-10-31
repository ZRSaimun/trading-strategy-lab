"""Offline, source-unverified prequential forecast drift review.

This is NOT a live worker, statistical significance test, alert sender, or
permission to place paper/live orders. All records must be independently
reconciled to the immutable prospective journal before operational use.
"""
import math
import re

_HORIZONS = (1, 3, 12)
_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\Z")
_FEED = {"instrument", "provider", "venue", "sourceId", "priceSide", "seconds"}
_KEYS = {"id", "modelVersion", "identity", "horizon", "baseStart", "issuedAt",
         "resolvedAt", "status", "probability", "outcomeUp"}
_STATUSES = {"PENDING", "SETTLED", "VOID_GAP"}


def _epoch(value):
    return type(value) is int and 0 <= value <= 2**53 - 1


def _identity(value):
    if type(value) is not dict or set(value) != _FEED:
        raise ValueError("Invalid exact feed identity")
    if any(type(value[k]) is not str or not 1 <= len(value[k]) <= 160 or
           value[k] != value[k].strip() for k in ("instrument", "provider", "venue", "sourceId")):
        raise ValueError("Invalid feed identity string")
    if type(value["priceSide"]) is not str or value["priceSide"] not in ("bid", "ask", "mid"):
        raise ValueError("Invalid feed price side")
    seconds = value["seconds"]
    if type(seconds) is not int or not 60 <= seconds <= 86400 or seconds % 60:
        raise ValueError("Invalid candle duration")


def audit_forecast_drift(records, *, identity, model_version, horizon,
                         cutover_at, as_of, min_samples=30, brier_worsening=0.05,
                         max_censored_fraction=0.1):
    """Compare preregistered chronological cohorts without overlapping outcomes.

    Drift flags are descriptive review triggers, NOT hypothesis-test p-values.
    Any censorship above the declared budget causes abstention. The caller is
    responsible for authenticating the source, record completeness, cutover,
    model version, and prospective registration of thresholds.
    """
    _identity(identity)
    if type(model_version) is not str or not _ID.fullmatch(model_version):
        raise ValueError("Invalid model version")
    if type(horizon) is not int or horizon not in _HORIZONS:
        raise ValueError("Invalid horizon")
    if not _epoch(cutover_at) or not _epoch(as_of) or cutover_at >= as_of:
        raise ValueError("Invalid evaluation clocks")
    if type(min_samples) is not int or not 30 <= min_samples <= 1000:
        raise ValueError("Invalid minimum sample count")
    if type(brier_worsening) not in (int, float) or not math.isfinite(brier_worsening) or not 0 <= brier_worsening <= 1:
        raise ValueError("Invalid Brier drift threshold")
    if type(max_censored_fraction) not in (int, float) or not math.isfinite(max_censored_fraction) or not 0 <= max_censored_fraction <= 1:
        raise ValueError("Invalid censorship budget")
    if type(records) is not list or len(records) > 5000:
        raise ValueError("Invalid forecast record collection")

    groups = {"reference": [], "recent": []}
    counts = {name: {"total": 0, "settled": 0, "pending": 0, "voidGap": 0,
                     "lateReference": 0, "overlapExcluded": 0} for name in groups}
    ids = set()
    for record in records:
        if type(record) is not dict or set(record) != _KEYS:
            raise ValueError("Malformed forecast record")
        fid = record["id"]
        if type(fid) is not str or not _ID.fullmatch(fid) or fid in ids:
            raise ValueError("Duplicate or invalid forecast ID")
        ids.add(fid)
        if record["identity"] != identity or record["modelVersion"] != model_version or record["horizon"] != horizon:
            raise ValueError("Mixed forecast source/model/horizon")
        base, issued, resolved = record["baseStart"], record["issuedAt"], record["resolvedAt"]
        if not _epoch(base) or base % identity["seconds"] or not _epoch(issued) or issued > as_of:
            raise ValueError("Invalid or future forecast issuance")
        target_end = base + (horizon + 1) * identity["seconds"]
        if not _epoch(target_end) or not base + identity["seconds"] <= issued < target_end:
            raise ValueError("Forecast not issued after completed base or before target")
        probability = record["probability"]
        if type(probability) not in (int, float) or not math.isfinite(probability) or not 0 < probability < 1:
            raise ValueError("Invalid forecast probability")
        status = record["status"]
        if type(status) is not str or status not in _STATUSES:
            raise ValueError("Invalid forecast outcome status")
        if status == "PENDING":
            if resolved is not None or record["outcomeUp"] is not None:
                raise ValueError("Pending outcome contains settlement")
        elif not _epoch(resolved) or resolved < issued or resolved > as_of:
            raise ValueError("Invalid or future resolution")
        elif status == "SETTLED":
            if resolved < target_end or type(record["outcomeUp"]) is not bool:
                raise ValueError("Settled outcome before target or not boolean")
        elif record["outcomeUp"] is not None:
            raise ValueError("Voided forecast has invented outcome")

        # The reference must have finished before the declared cutover. The
        # ambiguous crossing cohort is never silently assigned to recent.
        if issued < cutover_at and target_end <= cutover_at:
            cohort = "reference"
        elif issued >= cutover_at:
            cohort = "recent"
        else:
            continue
        counts[cohort]["total"] += 1
        if status == "PENDING":
            counts[cohort]["pending"] += 1
        elif status == "VOID_GAP":
            counts[cohort]["voidGap"] += 1
        elif cohort == "reference" and resolved > cutover_at:
            counts[cohort]["lateReference"] += 1
        else:
            groups[cohort].append((base, fid, float(probability), int(record["outcomeUp"])))

    result = {}
    for name, observations in groups.items():
        observations.sort(key=lambda row: (row[0], row[1]))
        accepted = []
        previous = None
        for row in observations:
            if previous is not None and row[0] < previous + horizon * identity["seconds"]:
                counts[name]["overlapExcluded"] += 1
                continue
            accepted.append(row)
            previous = row[0]
        counts[name]["settled"] = len(accepted)
        total = counts[name]["total"]
        censored = total - len(accepted)
        counts[name]["censoredFraction"] = censored / total if total else None
        counts[name]["brier"] = (sum((p - y) ** 2 for _, _, p, y in accepted) / len(accepted)
                                   if accepted else None)
        counts[name]["signedCalibrationError"] = (sum(p - y for _, _, p, y in accepted) / len(accepted)
                                                    if accepted else None)
        result[name] = counts[name]

    eligible = all(result[name]["settled"] >= min_samples and
                   result[name]["censoredFraction"] is not None and
                   result[name]["censoredFraction"] <= max_censored_fraction
                   for name in groups)
    delta = result["recent"]["brier"] - result["reference"]["brier"] if eligible else None
    status = ("INSUFFICIENT_OR_CENSORED" if not eligible else
              "DRIFT_REVIEW" if delta >= brier_worsening else "NO_THRESHOLD_BREACH")
    return {"status": status, "brierDelta": delta, "reference": result["reference"],
            "recent": result["recent"], "cutoverAt": cutover_at, "asOf": as_of,
            "threshold": float(brier_worsening), "minimumSamples": min_samples,
            "sourceAuthenticated": False, "recordCompletenessVerified": False,
            "statisticalSignificanceEstablished": False, "mayExecutePaperOrder": False,
            "mayExecuteLiveOrder": False}
