"""Synthetic timing-only tests. No historical returns or broker orders."""
import copy
import pytest
from app.walkforward_fold_audit import audit_development_walkforward as audit

YEAR = 365 * 86400
D = 86400
START = 1577836800  # 2020-01-01 UTC; synthetic elapsed windows


def fixtures():
    archives = [{"id": f"a{i}", "provider": "synthetic", "instrument": "XAUUSD-CFD",
                 "venue": "test", "priceSide": "bid", "utcConvention": "UTC",
                 "archiveSha256": f"{i+1:064x}", "start": START + i * YEAR,
                 "end": START + (i+1) * YEAR} for i in range(5)]
    protocol = {"developmentEnd": START + 3*YEAR, "validationEnd": START + 4*YEAR,
                "holdoutEnd": START + 5*YEAR, "embargoSeconds": 2*D,
                "strategyVersion": "frozen-v1", "configSha256": "a"*64}
    folds = [{"id": "fold1", "trainStart": START, "trainEnd": START+400*D,
              "testStart": START+403*D, "testEnd": START+450*D},
             {"id": "fold2", "trainStart": START, "trainEnd": START+600*D,
              "testStart": START+603*D, "testEnd": START+650*D}]
    def o(id, at, label=1, feature=0):
        a = next(a for a in archives if a["start"] <= at < a["end"])
        return {"id": id, "archiveId": a["id"], "featureStart": at-feature*D,
                "decisionAt": at, "labelAvailableAt": at+label*D}
    observations = [o("train", START+100*D), o("test1", START+410*D),
                    o("test2", START+610*D), o("validation", START+1150*D),
                    o("holdout", START+1500*D)]
    return archives, observations, protocol, folds, o


def run(mutate=None):
    a, o, p, f, maker = fixtures()
    if mutate:
        mutate(a, o, p, f, maker)
    return audit(a, o, p, f)


def test_disjoint_development_folds_do_not_inspect_validation_or_holdout():
    result = run()
    assert [f["testIds"] for f in result["folds"]] == [["test1"], ["test2"]]
    assert [f["trainIds"] for f in result["folds"]] == [["train"], ["train", "test1"]]
    assert result["validationHoldoutAccess"] is False and result["mayExecuteOrder"] is False
    assert result["archiveCount"] == 5


def test_future_holdout_metadata_does_not_change_fold_results():
    a, o, p, f, make = fixtures()
    before = audit(a, o, p, f)["folds"]
    o.append(make("new-future", START+1550*D))
    assert audit(a, o, p, f)["folds"] == before


def test_inputs_unchanged():
    a, o, p, f, _ = fixtures()
    before = copy.deepcopy((a, o, p, f))
    audit(a, o, p, f)
    assert (a, o, p, f) == before


@pytest.mark.parametrize("field,value", [("provider", "other"), ("priceSide", "ask"),
                                          ("venue", "other"), ("instrument", "NASDAQ")])
def test_source_drift_rejected(field, value):
    with pytest.raises(ValueError, match="Mixed source"):
        run(lambda a, o, p, f, m: a[2].__setitem__(field, value))


def test_archive_overlap_rejected():
    with pytest.raises(ValueError, match="Overlapping source"):
        run(lambda a, o, p, f, m: a[2].__setitem__("start", a[1]["end"]-1))


def test_duplicate_archive_digest_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        run(lambda a, o, p, f, m: a[2].__setitem__("archiveSha256", a[1]["archiveSha256"]))


def test_outcome_injection_rejected():
    with pytest.raises(ValueError, match="no outcomes"):
        run(lambda a, o, p, f, m: o[0].__setitem__("realizedR", 99))


def test_future_label_rejected():
    with pytest.raises(ValueError, match="noncausal"):
        run(lambda a, o, p, f, m: o[0].__setitem__("labelAvailableAt", o[0]["decisionAt"]-1))


def test_cross_archive_label_rejected():
    with pytest.raises(ValueError, match="cross-archive"):
        run(lambda a, o, p, f, m: o[0].__setitem__("labelAvailableAt", a[0]["end"]))


def test_test_label_embargo_edge():
    def modify(a, o, p, f, m):
        o.append(m("edge", f[0]["testStart"]+D))
        o[-1]["labelAvailableAt"] = f[0]["testEnd"]-p["embargoSeconds"]
        o.append(m("late", f[0]["testStart"]+2*D))
        o[-1]["labelAvailableAt"] = f[0]["testEnd"]-p["embargoSeconds"]+1
    r = run(modify)["folds"][0]
    assert "edge" in r["testIds"] and "late" not in r["testIds"]
    assert r["excludedCounts"]["TEST_LABEL_UNAVAILABLE_OR_EMBARGO"] == 1


def test_zero_embargo_still_excludes_label_at_test_end():
    def modify(a, o, p, f, m):
        p["embargoSeconds"] = 0
        o.append(m("boundary", f[0]["testStart"]+D))
        o[-1]["labelAvailableAt"] = f[0]["testEnd"]
    r = run(modify)["folds"][0]
    assert "boundary" not in r["testIds"]


def test_train_label_after_train_end_is_not_known():
    def modify(a, o, p, f, m):
        o.append(m("late-train", f[0]["trainEnd"]-D))
        o[-1]["labelAvailableAt"] = f[0]["trainEnd"]
    r = run(modify)["folds"][0]
    assert "late-train" not in r["trainIds"]
    assert r["excludedCounts"]["TRAIN_LABEL_UNAVAILABLE"] == 1


def test_cross_fold_feature_windows_excluded():
    def modify(a, o, p, f, m):
        o.append(m("lookback", f[0]["testStart"]+D, feature=2))
    r = run(modify)["folds"][0]
    assert "lookback" not in r["testIds"]
    assert r["excludedCounts"]["TEST_FEATURE_CROSSES_START"] == 1


@pytest.mark.parametrize("change", [
    lambda a,o,p,f,m: f[1].__setitem__("testStart", f[0]["testEnd"]-1),
    lambda a,o,p,f,m: f[1].__setitem__("testEnd", p["validationEnd"]),
    lambda a,o,p,f,m: f[0].__setitem__("testStart", f[0]["trainEnd"]+D),
    lambda a,o,p,f,m: f[1].__setitem__("id", f[0]["id"]),
])
def test_invalid_fold_rejected(change):
    with pytest.raises(ValueError, match="Fold overlaps"):
        run(change)


def test_empty_test_is_not_successful_evidence():
    def modify(a, o, p, f, m):
        o[:] = [o[0]]
    assert run(modify)["folds"][0]["status"] == "INSUFFICIENT_TIMING_OBSERVATIONS"


def test_archive_gap_disclosed_not_silently_repaired():
    def modify(a, o, p, f, m):
        a[2]["start"] += D
    assert run(modify)["declaredArchiveGaps"] == 1


def test_bool_timestamp_rejected():
    with pytest.raises(ValueError, match="Fold overlaps"):
        run(lambda a,o,p,f,m: f[0].__setitem__("testEnd", True))


def test_too_many_folds_rejected():
    with pytest.raises(ValueError, match="unbounded"):
        run(lambda a,o,p,f,m: f.extend([f[0].copy() for _ in range(100)]))
