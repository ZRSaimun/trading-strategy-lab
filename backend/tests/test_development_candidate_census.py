"""Synthetic development-only candidate census tests; no actual returns."""
import copy
import pytest
from app.development_candidate_census import (
    audit_development_candidate_census as audit,
    candidate_registration_digest,
)

DAY = 86400
YEAR = 365 * DAY
START = 1577836800


def fixture():
    archives = [{"id": f"a{i}", "provider": "invented", "instrument": "XAUUSD-CFD",
                 "venue": "synthetic", "priceSide": "bid_ask", "utcConvention": "UTC",
                 "archiveSha256": f"{i+1:064x}", "start": START+i*YEAR,
                 "end": START+(i+1)*YEAR} for i in range(5)]
    protocol = {"developmentEnd": START+3*YEAR, "validationEnd": START+4*YEAR,
                "holdoutEnd": START+5*YEAR, "embargoSeconds": DAY,
                "strategyVersion": "invented", "configSha256": "a"*64}
    folds = [{"id": "f1", "trainStart": START, "trainEnd": START+400*DAY,
              "testStart": START+402*DAY, "testEnd": START+450*DAY},
             {"id": "f2", "trainStart": START, "trainEnd": START+600*DAY,
              "testStart": START+602*DAY, "testEnd": START+650*DAY}]
    def obs(id, at):
        archive = next(a for a in archives if a["start"] <= at < a["end"])
        return {"id": id, "archiveId": archive["id"], "featureStart": at,
                "decisionAt": at, "labelAvailableAt": at+DAY}
    observations = [obs("train", START+100*DAY), obs("t1", START+410*DAY),
                    obs("t2", START+610*DAY), obs("validation", START+1150*DAY),
                    obs("holdout", START+1500*DAY)]
    candidates = [{"id": "A", "configSha256": "b"*64},
                  {"id": "B", "configSha256": "c"*64}]
    registration = {"registeredAt": START+200*DAY,
                    "manifestSha256": candidate_registration_digest(archives, observations, protocol, folds, candidates)}
    from app.walkforward_fold_audit import audit_development_walkforward
    from app.development_candidate_census import _hash
    timing = audit_development_walkforward(archives, observations, protocol, folds)
    source = _hash({"source": timing["source"], "archiveLineage": timing["archiveLineage"]})
    trials = []
    for c in candidates:
        for f in timing["folds"]:
            trials.append({"candidateId": c["id"], "foldId": f["id"],
                           "configSha256": c["configSha256"], "sourceSha256": source,
                           "testSetSha256": _hash(sorted(f["testIds"])),
                           "score": "0.10" if c["id"] == "A" else "0.20",
                           "observedAt": f["bounds"]["testEnd"]+DAY})
    selection = {"candidateId": "B", "selectedConfigSha256": "c"*64,
                 "selectedAt": START+660*DAY, "candidateCount": 2,
                 "trialCount": 4, "policy": "max_equal_fold_mean_tie_lexicographic_id"}
    return [archives, observations, protocol, folds, candidates, registration, trials, selection]


def run(mutate=None):
    inputs = fixture()
    if mutate:
        mutate(*inputs)
    return audit(*inputs)


def test_complete_census_is_declared_only_and_never_executable():
    result = run()
    assert result["status"] == "DECLARED_ONLY"
    assert (result["candidateCount"], result["foldCount"], result["trialCount"]) == (2, 2, 4)
    assert result["selectedCandidateId"] == "B"
    assert result["declaredMeanScores"] == {"A": "0.10", "B": "0.20"}
    assert result["mayExecuteLiveOrder"] is False
    assert result["mayExecutePaperOrder"] is False
    assert result["preregistrationExternallyVerified"] is False
    assert result["candidateCompletenessExternallyVerified"] is False


def test_inputs_are_not_mutated():
    inputs = fixture()
    before = copy.deepcopy(inputs)
    audit(*inputs)
    assert inputs == before


def test_holdout_metadata_does_not_change_registration_or_scores():
    a, o, p, f, c, reg, trials, selection = fixture()
    old = audit(a, o, p, f, c, reg, trials, selection)
    o.append({"id": "future-extra", "archiveId": "a4",
              "featureStart": START+1510*DAY, "decisionAt": START+1510*DAY,
              "labelAvailableAt": START+1511*DAY})
    # The manifest intentionally excludes unused holdout observations.
    # Development ranking must remain unchanged without reading future outcomes.
    new = audit(a, o, p, f, c, reg, trials, selection)
    assert new == old
    assert old["validationHoldoutAccess"] is False


@pytest.mark.parametrize("mutation", [
    lambda a,o,p,f,c,r,t,s: t.pop(),
    lambda a,o,p,f,c,r,t,s: t.__setitem__(1, copy.deepcopy(t[0])),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("candidateId", "unknown"),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("configSha256", "d"*64),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("sourceSha256", "d"*64),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("testSetSha256", "d"*64),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("observedAt", f[0]["testEnd"]),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("observedAt", p["developmentEnd"]),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("score", "NaN"),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("score", "1e500"),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("score", "0.1234567"),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("score", "1000001"),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("score", 0.2),
    lambda a,o,p,f,c,r,t,s: t[0].__setitem__("profit", "999"),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("candidateId", "A"),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("selectedConfigSha256", "b"*64),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("selectedAt", t[-1]["observedAt"]-1),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("selectedAt", p["developmentEnd"]),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("candidateCount", True),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("trialCount", 3),
    lambda a,o,p,f,c,r,t,s: s.__setitem__("policy", "manual"),
    lambda a,o,p,f,c,r,t,s: r.__setitem__("registeredAt", f[0]["testStart"]),
    lambda a,o,p,f,c,r,t,s: r.__setitem__("manifestSha256", "d"*64),
    lambda a,o,p,f,c,r,t,s: c[1].__setitem__("configSha256", c[0]["configSha256"]),
    lambda a,o,p,f,c,r,t,s: f[1].__setitem__("testEnd", p["holdoutEnd"]),
    lambda a,o,p,f,c,r,t,s: o[0].__setitem__("realizedReturn", "0.99"),
])
def test_fail_closed_on_census_identity_clock_and_holdout_leakage(mutation):
    with pytest.raises(ValueError):
        run(mutation)


def test_tie_break_is_deterministic():
    a, o, p, f, c, r, t, s = fixture()
    for trial in t:
        trial["score"] = "0.10"
    s["candidateId"] = "A"
    s["selectedConfigSha256"] = "b"*64
    assert audit(a, o, p, f, c, r, t, s)["selectedCandidateId"] == "A"


def test_order_independent_candidate_roster_manifest():
    a, o, p, f, c, r, t, s = fixture()
    c.reverse()
    assert candidate_registration_digest(a, o, p, f, c) == r["manifestSha256"]


def test_reject_incomplete_fold_before_scoring():
    a, o, p, f, c, r, t, s = fixture()
    o[:] = [o[0]]
    with pytest.raises(ValueError, match="Insufficient"):
        audit(a, o, p, f, c, r, t, s)
