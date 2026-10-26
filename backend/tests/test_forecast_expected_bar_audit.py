"""Disconnected, synthetic expected completed-candle register checks."""
import copy
import pytest

from app.forecast_expected_bar_audit import audit_expected_completed_bars as audit


IDENTITY = {"instrument": "XAUUSD-TEST", "provider": "SYNTH", "venue": "OFFLINE",
            "sourceId": "fixture", "priceSide": "bid", "seconds": 60}


def snapshot(starts=(0, 60, 240)):
    return {"evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL",
            "identity": copy.deepcopy(IDENTITY),
            "events": [{"kind": "CANDLE", "seq": i, "receivedAt": s + 60,
                        "start": s, "close": 100.0} for i, s in enumerate(starts, 1)]}


def check(starts=None, journal=None, now=300, identity=None):
    return audit(snapshot() if journal is None else journal,
                 IDENTITY if identity is None else identity,
                 [0, 60, 240] if starts is None else starts, as_of=now)


def test_session_break_is_declared_not_inferred():
    report = check()
    assert report["declaredExpectedBarCount"] == 3
    assert report["status"] == "DECLARED_MATCH_UNVERIFIED"
    assert all(report[k] is False for k in ("independentlyComplete", "providerAuthenticated",
        "sessionCalendarAuthenticated", "maySendNotification", "mayExecutePaperOrder",
        "mayExecuteLiveOrder"))


def test_does_not_mutate_inputs():
    row, feed, expected = snapshot(), copy.deepcopy(IDENTITY), [0, 60, 240]
    before = copy.deepcopy((row, feed, expected))
    audit(row, feed, expected, as_of=300)
    assert (row, feed, expected) == before


@pytest.mark.parametrize("starts", [[0, 60], [0, 60, 120, 240], [0, 240, 60],
                                     [0, 60, 60, 240], [0, 60, 241], [], [True, 60, 240]])
def test_invalid_or_mismatched_expected_register(starts):
    with pytest.raises(ValueError):
        check(starts=starts)


@pytest.mark.parametrize("observed", [[0, 60], [0, 60, 120, 240], [0, 240, 60],
                                      [0, 60, 60, 240]])
def test_missing_extra_backward_duplicate_journal(observed):
    with pytest.raises(ValueError):
        check(journal=snapshot(observed))


@pytest.mark.parametrize("bad", [True, -1, 1.5, 2**53])
def test_invalid_audit_clock(bad):
    with pytest.raises(ValueError, match="audit time"):
        check(now=bad)


def test_unfinished_expected_bar_fails():
    with pytest.raises(ValueError, match="incomplete"):
        check(now=299)


def test_late_received_bar_fails():
    row = snapshot()
    row["events"][2]["receivedAt"] = 301
    with pytest.raises(ValueError, match="chronology"):
        check(journal=row)


def test_uncompleted_bar_receipt_fails():
    row = snapshot()
    row["events"][1]["receivedAt"] = 61
    with pytest.raises(ValueError, match="chronology"):
        check(journal=row)


def test_identity_mismatch_fails():
    with pytest.raises(ValueError, match="register or journal"):
        check(identity={**IDENTITY, "priceSide": "ask"})


def test_forged_evidence_fails():
    row = snapshot()
    row["evidence"] = "AUTHENTICATED_LIVE"
    with pytest.raises(ValueError, match="register or journal"):
        check(journal=row)


def test_unknown_candle_field_fails():
    row = snapshot()
    row["events"][0]["deliveryVerified"] = True
    with pytest.raises(ValueError, match="Malformed"):
        check(journal=row)


def test_forecast_events_are_ignored_not_scored():
    row = snapshot()
    row["events"].append({"kind": "FORECAST", "id": "f1"})
    assert check(journal=row)["mayExecuteLiveOrder"] is False


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), 0, -1, True])
def test_invalid_completed_candle_price_fails(bad):
    row = snapshot()
    row["events"][0]["close"] = bad
    with pytest.raises(ValueError, match="chronology"):
        check(journal=row)
