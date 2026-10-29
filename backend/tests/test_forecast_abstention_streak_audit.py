"""Synthetic zero-network tests for declared forecast abstention streaks."""
from copy import deepcopy

import pytest

from app.forecast_abstention_streak_audit import (
    _streaks, audit_forecast_abstention_streaks as audit)

IDENTITY = {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH",
            "venue": "TEST", "sourceId": "streak-test", "priceSide": "bid",
            "seconds": 60}


def keys(n=60, *, model="m1", horizon=1, offset=0):
    return [(model, horizon, (i + offset + 1) * 60) for i in range(n)]


def abstain(key, reason="DATA_QUALITY"):
    model, horizon, base = key
    return {"modelVersion": model, "horizon": horizon, "baseStart": base,
            "decisionAt": base + 60, "reason": reason}


def snapshot(forecast_keys):
    events, forecasts = [], []
    for i, (model, horizon, base) in enumerate(forecast_keys):
        fid = f"f{i}"
        events.append({"kind": "FORECAST", "id": fid, "modelVersion": model,
                       "horizon": horizon, "probability": .6,
                       "baseStart": base, "receivedAt": base + 60})
        forecasts.append({"id": fid, "modelVersion": model, "horizon": horizon,
                          "probability": .6, "baseStart": base, "baseClose": 100.,
                          "issuedAt": base + 60, "targetStart": base + horizon * 60,
                          "status": "PENDING", "resolvedAt": None, "outcomeUp": None})
    return {"sequence": len(events), "identity": deepcopy(IDENTITY),
            "maxLagSeconds": 30, "events": events, "forecasts": forecasts,
            "evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL"}


def evaluate(expected, absent=(), **kwargs):
    absent = list(absent)
    missing = {(a["modelVersion"], a["horizon"], a["baseStart"]) for a in absent}
    return audit(snapshot([k for k in expected if k not in missing]),
                 IDENTITY, expected, absent,
                 as_of=max((k[2] for k in expected), default=0) + 120, **kwargs)


def test_all_forecasts_clean_unverified():
    r = evaluate(keys())
    assert r["status"] == "DECLARED_ABSTENTION_STREAKS_WITHIN_WARNING_UNVERIFIED"
    assert r["byModelHorizon"][0]["longestAbstentionStreak"] == 0
    assert r["byModelHorizon"][0]["trailingAbstentionStreak"] == 0
    assert r["groupsWithWarning"] == 0
    assert all(r[k] is False for k in (
        "sourceAuthenticated", "scheduleIndependentlyVerified",
        "abstentionsIndependentlyVerified", "recipientDeliveryVerified",
        "maySendNotification", "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_contiguous_warning_and_span_and_trailing():
    expected = keys()
    r = evaluate(expected, [abstain(k) for k in expected[-12:]])
    g = r["byModelHorizon"][0]
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert g["longestAbstentionStreak"] == 12
    assert g["longestAbstentionStreakBaseStarts"] == [49 * 60, 60 * 60]
    assert g["trailingAbstentionStreak"] == 12
    assert g["longestSameReasonStreak"] == 12


def test_threshold_is_inclusive_and_tunable():
    expected = keys()
    missing = [abstain(k) for k in expected[-4:]]
    assert evaluate(expected, missing, warning_consecutive_abstentions=4)["groupsWithWarning"] == 1
    assert evaluate(expected, missing, warning_consecutive_abstentions=5)["groupsWithWarning"] == 0


def test_mixed_reasons_and_nontrailing_streak():
    expected = keys()
    missing = [abstain(k, "LOW_CONFIDENCE" if i < 5 else "DATA_QUALITY")
               for i, k in enumerate(expected[10:20])]
    g = evaluate(expected, missing)["byModelHorizon"][0]
    assert g["longestAbstentionStreak"] == 10
    assert g["longestSameReasonStreak"] == 5
    assert g["longestSameReasonStreakReason"] == "LOW_CONFIDENCE"
    assert g["trailingAbstentionStreak"] == 0


def test_schedule_gap_breaks_run_not_just_list_adjacency():
    bases = [60, 120, 180, 600, 660]
    r = _streaks(bases, {b: "DATA_QUALITY" for b in bases}, 60)
    assert r["longestAbstentionStreak"] == 3
    assert r["longestAbstentionStreakBaseStarts"] == [60, 180]
    assert r["trailingAbstentionStreak"] == 2


def test_reordered_input_does_not_change_report_or_mutate():
    expected = keys()
    missing = [abstain(k) for k in expected[20:35]]
    s = snapshot([k for k in expected if k not in expected[20:35]])
    before = deepcopy((s, expected, missing))
    a = audit(s, IDENTITY, expected, missing, as_of=4000)
    b = audit(s, IDENTITY, list(reversed(expected)),
              list(reversed(missing)), as_of=4000)
    assert a == b
    assert (s, expected, missing) == before


def test_model_and_horizon_isolation():
    expected = keys(model="a") + keys(model="b", horizon=12)
    missing = [abstain(k) for k in expected[-12:]]
    r = evaluate(expected, missing)
    assert r["eligibleModelHorizonGroups"] == 2
    assert r["groupsWithWarning"] == 1
    assert [g["longestAbstentionStreak"] for g in r["byModelHorizon"]] == [0, 12]


def test_short_population_withheld():
    r = evaluate(keys(29))
    assert r["status"] == "INSUFFICIENT_COMPLETE_DECLARED_SAMPLE"
    assert r["groupsWithWarning"] == 0
    assert r["byModelHorizon"] == []


def test_no_expected_does_not_claim_healthy():
    r = evaluate([])
    assert r["status"] == "NO_DECLARED_EXPECTATIONS"
    assert r["groupsWithWarning"] is None


def test_missing_decision_withholds_every_group():
    expected = keys()
    r = audit(snapshot(expected[:-1]), IDENTITY, expected, [], as_of=4000)
    assert r["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert r["groupsWithWarning"] is None
    assert r["byModelHorizon"] == []


def test_conflicting_decision_withholds_every_group():
    expected = keys()
    r = audit(snapshot(expected), IDENTITY, expected,
              [abstain(expected[0])], as_of=4000)
    assert r["byModelHorizon"] == []


def test_unexpected_abstention_withholds_every_group():
    expected = keys()
    r = evaluate(expected, [abstain(("m1", 1, 61 * 60))])
    assert r["byModelHorizon"] == []


@pytest.mark.parametrize("minimum,warning", [
    (True, 12), (29, 12), (5001, 12), (30., 12),
    (30, True), (30, 1), (30, 5001), (30, 12.),
])
def test_invalid_configuration_fails_closed(minimum, warning):
    with pytest.raises(ValueError):
        evaluate(keys(), min_decisions_per_group=minimum,
                 warning_consecutive_abstentions=warning)


def test_invalid_reason_rejected():
    expected = keys()
    with pytest.raises(ValueError):
        evaluate(expected, [abstain(expected[0], "UNKNOWN")])


def test_forged_journal_evidence_rejected():
    expected = keys()
    s = snapshot(expected)
    s["evidence"] = "VERIFIED_LIVE"
    with pytest.raises(ValueError):
        audit(s, IDENTITY, expected, [], as_of=4000)
