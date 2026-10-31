"""Synthetic, offline, no-network review message regressions."""
from copy import deepcopy
import pytest

from app.forecast_review_message import render_unverified_forecast_review


def fixture():
    feed = {"instrument": "XAUUSD-SYNTH", "provider": "TEST", "venue": "SIM",
            "sourceId": "synthetic", "priceSide": "bid", "seconds": 60}
    row = {"id": "jf_a", "modelVersion": "baseline-v1", "horizon": 3,
           "probability": .6, "baseStart": 60, "targetStart": 240,
           "issuedAt": 120, "status": "PENDING", "outcomeUp": None, "resolvedAt": None}
    event = {"seq": 2, "receivedAt": 120, "kind": "FORECAST", "id": "jf_a",
             "modelVersion": "baseline-v1", "horizon": 3, "probability": .6, "baseStart": 60}
    snap = {"evidence": "UNAUTHENTICATED_DISCONNECTED_SERVER_JOURNAL",
            "identity": feed, "forecasts": [row], "events": [event]}
    view = {"forecastId": "jf_a", "issueSeq": 2, "status": "QUEUED", "expiresAt": 200,
            "sourceAuthenticated": False, "deliveryVerified": False,
            "notificationEnabled": False, "mayExecutePaperOrder": False,
            "mayExecuteLiveOrder": False}
    return snap, view


def render(s, v, at=125):
    return render_unverified_forecast_review(s, v, forecast_id="jf_a", as_of=at)


def test_safe_bounded_unverified_message():
    s, v = fixture()
    msg = render(s, v)
    assert "UNVERIFIED RESEARCH" in msg and "UNCALIBRATED" in msg
    assert "NOT an executable quote" in msg and "NO BUY/SELL SIGNAL" in msg
    assert "NO PAPER OR LIVE ORDER" in msg and "60.00%" in msg
    assert "1970-01-01" in msg and len(msg) <= 1000
    assert "LIVE BUY" not in msg and "DELIVERED" not in msg


def test_uncertain_claim_does_not_assert_delivery():
    s, v = fixture()
    v["status"] = "IN_FLIGHT_UNCERTAIN"
    assert "NOT LIVE" in render(s, v)


@pytest.mark.parametrize("field,value", [
    ("status", "ACK_RECORDED_UNVERIFIED"), ("status", "EXPIRED_UNCLAIMED"),
    ("forecastId", "other"), ("issueSeq", 3), ("sourceAuthenticated", True),
    ("deliveryVerified", True), ("notificationEnabled", True),
    ("mayExecutePaperOrder", True), ("mayExecuteLiveOrder", True),
])
def test_invalid_outbox_view_fails(field, value):
    s, v = fixture()
    v[field] = value
    with pytest.raises(ValueError):
        render(s, v)


@pytest.mark.parametrize("field,value", [
    ("status", "SETTLED"), ("probability", 1), ("probability", float("nan")),
    ("horizon", 2), ("outcomeUp", True), ("resolvedAt", 130),
    ("targetStart", 300), ("issuedAt", 300), ("baseStart", 61),
    ("modelVersion", "model\nLIVE BUY"),
])
def test_invalid_forecast_fails(field, value):
    s, v = fixture()
    s["forecasts"][0][field] = value
    with pytest.raises(ValueError):
        render(s, v)


@pytest.mark.parametrize("field,value", [
    ("provider", "TEST\nLIVE BUY"), ("instrument", "XAUUSD\rSELL"),
    ("sourceId", "a" * 81), ("priceSide", "trade"), ("seconds", 61),
])
def test_source_injection_or_invalid_feed_fails(field, value):
    s, v = fixture()
    s["identity"][field] = value
    with pytest.raises(ValueError):
        render(s, v)


def test_expired_or_post_target_fails():
    s, v = fixture()
    with pytest.raises(ValueError, match="expired"):
        render(s, v, 200)
    v["expiresAt"] = 1000
    with pytest.raises(ValueError, match="chronology"):
        render(s, v, 300)


def test_missing_or_duplicate_linkage_fails():
    s, v = fixture()
    s["forecasts"].append(deepcopy(s["forecasts"][0]))
    with pytest.raises(ValueError):
        render(s, v)
    s, v = fixture()
    s["events"] = []
    with pytest.raises(ValueError):
        render(s, v)


def test_event_identity_mismatch_fails():
    s, v = fixture()
    s["events"][0]["probability"] = .7
    with pytest.raises(ValueError, match="mismatch"):
        render(s, v)


def test_untrusted_evidence_rejected():
    s, v = fixture()
    s["evidence"] = "AUTHENTICATED_LIVE"
    with pytest.raises(ValueError):
        render(s, v)


@pytest.mark.parametrize("probability,expected", [
    (1e-12, "<0.01%"),
    (0.000099, "<0.01%"),
    (0.0001, "0.01%"),
    (0.9999, "99.99%"),
    (0.999901, ">99.99%"),
    (1 - 1e-12, ">99.99%"),
])
def test_extreme_nonzero_probabilities_never_render_as_zero_or_certain(probability, expected):
    s, v = fixture()
    s["forecasts"][0]["probability"] = probability
    s["events"][0]["probability"] = probability
    msg = render(s, v)
    assert f"P(up vs base close): {expected} (UNCALIBRATED)" in msg
    assert "0.00%" not in msg
    assert "100.00%" not in msg


def test_expiry_must_not_outlive_target_completed_candle():
    s, v = fixture()
    # The outbox queue clamps expiry to targetStart + candle seconds.
    # A forged/stale view must not advertise validity beyond that boundary.
    v["expiresAt"] = 301
    with pytest.raises(ValueError, match="chronology"):
        render(s, v)
    v["expiresAt"] = 300
    assert "NOT LIVE" in render(s, v)
