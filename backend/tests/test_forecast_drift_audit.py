"""Synthetic offline acceptance for descriptive forecast drift gating."""
import copy
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.forecast_drift_audit import audit_forecast_drift

FEED = {"instrument": "XAUUSD", "provider": "synthetic", "venue": "TEST",
        "sourceId": "no-live-source", "priceSide": "bid", "seconds": 60}
CUT = 100_000 * 60
AS_OF = CUT + 10_000 * 60


def record(index, cohort, probability=0.5, outcome=True, status="SETTLED"):
    base = CUT - (200 + index * 14) * 60 if cohort == "reference" else CUT + (index * 14) * 60
    target_end = base + 13 * 60
    return {"id": f"{cohort}-{index}", "modelVersion": "v1", "identity": copy.deepcopy(FEED),
            "horizon": 12, "baseStart": base, "issuedAt": base + 60,
            "resolvedAt": target_end if status != "PENDING" else None,
            "status": status, "probability": probability,
            "outcomeUp": outcome if status == "SETTLED" else None}


def evaluate(rows, **overrides):
    args = {"identity": FEED, "model_version": "v1", "horizon": 12,
            "cutover_at": CUT, "as_of": AS_OF}
    args.update(overrides)
    return audit_forecast_drift(rows, **args)


def cohorts(p1=0.8, p2=0.8, y=True, count=30):
    return [record(i, "reference", p1, y) for i in range(count)] + [
        record(i, "recent", p2, y) for i in range(count)]


def test_descriptive_drift_review_on_worsening_brier():
    report = evaluate(cohorts(p1=0.9, p2=0.1))
    assert report["status"] == "DRIFT_REVIEW"
    assert report["brierDelta"] > 0.7
    assert report["reference"]["settled"] == report["recent"]["settled"] == 30
    assert report["mayExecuteLiveOrder"] is False
    assert report["sourceAuthenticated"] is False
    assert report["statisticalSignificanceEstablished"] is False


def test_no_threshold_breach_not_permission_to_trade():
    report = evaluate(cohorts())
    assert report["status"] == "NO_THRESHOLD_BREACH"
    assert report["brierDelta"] == 0
    assert not report["mayExecutePaperOrder"]


def test_minimum_samples_abstain():
    report = evaluate(cohorts(count=29))
    assert report["status"] == "INSUFFICIENT_OR_CENSORED"
    assert report["brierDelta"] is None


def test_pending_void_and_late_reference_prevent_cherry_picking():
    rows = cohorts()
    rows[0]["resolvedAt"] = CUT + 60
    rows[1]["status"] = "PENDING"
    rows[1]["resolvedAt"] = None
    rows[1]["outcomeUp"] = None
    rows[2]["status"] = "VOID_GAP"
    rows[2]["outcomeUp"] = None
    report = evaluate(rows)
    assert report["reference"]["lateReference"] == 1
    assert report["reference"]["pending"] == 1
    assert report["reference"]["voidGap"] == 1
    assert report["status"] == "INSUFFICIENT_OR_CENSORED"


def test_crossing_cutover_not_assigned_to_either_cohort():
    rows = cohorts()
    crossing = record(999, "recent")
    crossing.update(id="crossing", baseStart=CUT - 120, issuedAt=CUT - 60,
                    resolvedAt=CUT + 11 * 60)
    report = evaluate(rows + [crossing])
    assert report["reference"]["total"] == report["recent"]["total"] == 30


def test_overlapping_outcomes_are_excluded_and_counted():
    rows = cohorts()
    extra = record(999, "recent")
    extra.update(id="overlap", baseStart=CUT + 60, issuedAt=CUT + 120,
                 resolvedAt=CUT + 14 * 60)
    report = evaluate(rows + [extra])
    assert report["recent"]["overlapExcluded"] == 1
    assert report["recent"]["total"] == 31


@pytest.mark.parametrize("field,value", [
    ("probability", 0), ("probability", 1), ("probability", float("nan")),
    ("probability", True), ("issuedAt", AS_OF + 1), ("issuedAt", False),
    ("resolvedAt", AS_OF + 1), ("outcomeUp", 1), ("horizon", True),
    ("status", "PROFIT"), ("baseStart", CUT + 1),
])
def test_invalid_record_fails_closed(field, value):
    rows = cohorts()
    rows[0][field] = value
    with pytest.raises(ValueError):
        evaluate(rows)


def test_duplicate_ids_fail_closed():
    rows = cohorts()
    rows[1]["id"] = rows[0]["id"]
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate(rows)


def test_mixed_feed_fails_closed():
    rows = cohorts()
    rows[0]["identity"]["provider"] = "other"
    with pytest.raises(ValueError, match="Mixed"):
        evaluate(rows)


def test_settled_before_target_fails_closed():
    rows = cohorts()
    rows[0]["resolvedAt"] = rows[0]["issuedAt"]
    with pytest.raises(ValueError, match="before target"):
        evaluate(rows)


@pytest.mark.parametrize("key,value", [("min_samples", 29), ("min_samples", True),
                                       ("brier_worsening", -0.1),
                                       ("max_censored_fraction", float("nan")),
                                       ("cutover_at", AS_OF)])
def test_bad_policy_fails_closed(key, value):
    with pytest.raises(ValueError):
        evaluate(cohorts(), **{key: value})


def test_excessive_censorship_abstains_even_with_30_settled():
    rows = cohorts(count=40)
    for row in rows:
        if row["id"].startswith("recent") and int(row["id"].split("-")[-1]) < 10:
            row.update(status="VOID_GAP", outcomeUp=None)
    report = evaluate(rows)
    assert report["recent"]["settled"] == 30
    assert report["recent"]["censoredFraction"] == 0.25
    assert report["status"] == "INSUFFICIENT_OR_CENSORED"
