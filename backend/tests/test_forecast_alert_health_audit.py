"""Synthetic, standalone alert-backlog health regression tests."""
import copy
import pytest
from app.forecast_alert_health_audit import audit_forecast_alert_health as audit


def state(status="QUEUED", **changes):
    row = {"version": 1, "identity": {"instrument": "XAUUSD-SYNTH", "provider": "SYNTH",
           "venue": "TEST", "sourceId": "offline", "priceSide": "bid", "seconds": 60},
           "forecastId": "f1", "modelVersion": "baseline", "horizon": 3,
           "baseStart": 60, "issueSeq": 2, "issuedAt": 120, "expiresAt": 300,
           "status": status, "claimId": None, "claimedAt": None, "ackAt": None}
    if status in ("IN_FLIGHT_UNCERTAIN", "ACK_RECORDED_UNVERIFIED"):
        row.update(claimId="a" * 32, claimedAt=130)
    if status == "ACK_RECORDED_UNVERIFIED":
        row["ackAt"] = 140
    row.update(changes)
    return row


def check(row=None, now=150, expected=None, records=None, **kw):
    records = [{"sessionId": "s1", "state": row or state()}] if records is None else records
    expected = [("s1", "f1")] if expected is None else expected
    return audit(records, expected, as_of=now, **kw)


def test_queued_healthy_and_no_authority():
    result = check()
    assert result["counts"]["QUEUED"] == 1
    assert result["status"] == "DECLARED_ONLY"
    assert all(result[k] is False for k in ("maySendNotification", "providerDeliveryVerified",
        "recipientDeliveryVerified", "mayExecutePaperOrder", "mayExecuteLiveOrder"))


def test_queued_warning():
    result = check(now=180)
    assert result["counts"]["QUEUE_DELAY_WARNING"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["warningKeys"] == [["s1", "f1"]]


def test_expired_queued():
    result = check(now=300)
    assert result["counts"]["EXPIRED_UNCLAIMED"] == 1
    assert result["counts"]["QUEUED"] == 0


def test_uncertain_claim_never_safe_to_retry():
    result = check(state("IN_FLIGHT_UNCERTAIN"), now=150)
    assert result["counts"]["IN_FLIGHT_UNCERTAIN"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["counts"]["UNCERTAIN_DELAY_WARNING"] == 0
    assert result["maySendNotification"] is False


def test_old_uncertain_claim_warning():
    result = check(state("IN_FLIGHT_UNCERTAIN"), now=160)
    assert result["oldestUncertainSeconds"] == 30
    assert result["counts"]["UNCERTAIN_DELAY_WARNING"] == 1


def test_ack_never_counts_as_human_delivery():
    result = check(state("ACK_RECORDED_UNVERIFIED"))
    assert result["counts"]["ACK_RECORDED_UNVERIFIED"] == 1
    assert result["maxSelfAttestedAckLagSeconds"] == 10
    assert result["providerDeliveryVerified"] is False
    assert result["recipientDeliveryVerified"] is False


def test_cancelled():
    assert check(state("CANCELLED"))["counts"]["CANCELLED"] == 1


def test_empty_population_is_not_green():
    result = check(records=[], expected=[])
    assert result["status"] == "NO_DECLARED_ALERTS"
    assert result["declaredCount"] == 0


def test_order_independent_census():
    second = state(forecastId="f2", status="IN_FLIGHT_UNCERTAIN")
    a = [{"sessionId": "s1", "state": state()}, {"sessionId": "s1", "state": second}]
    b = list(reversed(a))
    expected = [("s1", "f1"), ("s1", "f2")]
    assert check(records=a, expected=expected) == check(records=b, expected=list(reversed(expected)))


def test_missing_and_extra_rejected():
    with pytest.raises(ValueError, match="Incomplete"):
        check(records=[], expected=[("s1", "f1")])
    with pytest.raises(ValueError, match="undeclared"):
        check(records=[{"sessionId": "s1", "state": state()}], expected=[])


def test_duplicate_population_rejected():
    row = {"sessionId": "s1", "state": state()}
    with pytest.raises(ValueError, match="Duplicate or undeclared"):
        check(records=[row, row])
    with pytest.raises(ValueError, match="Duplicate expected"):
        check(expected=[("s1", "f1"), ("s1", "f1")])


@pytest.mark.parametrize("mutation", [
    lambda s: s.update(status="DELIVERED"),
    lambda s: s.update(status=[]),
    lambda s: s.update(ackAt=130),
    lambda s: s.update(claimId="a" * 32),
    lambda s: s.update(issueSeq=True),
    lambda s: s.update(version=True),
    lambda s: s.update(expiresAt=100),
    lambda s: s.update(issuedAt=500),
    lambda s: s.update(horizon=2),
    lambda s: s.update(identity={**s["identity"], "seconds": 61}),
    lambda s: s.update(extra="spoof"),
])
def test_invalid_states_fail_closed(mutation):
    row = state()
    mutation(row)
    with pytest.raises(ValueError, match="Invalid alert health state"):
        check(row)


@pytest.mark.parametrize("expiry", [120, 120 + 3601])
def test_impossible_outbox_expiry_fails_closed(expiry):
    with pytest.raises(ValueError, match="Invalid alert health state"):
        check(state(expiresAt=expiry))


def test_maximum_allowed_outbox_age_is_accepted_without_send_authority():
    # A 1-hour alert lifetime requires a target candle that closes late enough.
    feed = {**state()["identity"], "seconds": 3600}
    row = state(identity=feed, baseStart=3600, issuedAt=7200,
                expiresAt=10800, horizon=1)
    result = check(row, now=7250)
    assert result["status"] == "DECLARED_ONLY"
    assert result["maySendNotification"] is False


def test_inconsistent_claim_fails_closed():
    with pytest.raises(ValueError, match="Invalid alert health state"):
        check(state("IN_FLIGHT_UNCERTAIN", claimedAt=301))
    with pytest.raises(ValueError, match="Invalid alert health state"):
        check(state("ACK_RECORDED_UNVERIFIED", ackAt=129))


@pytest.mark.parametrize("bad", [True, -1, 1.5, 2**53])
def test_invalid_as_of_rejected(bad):
    with pytest.raises(ValueError, match="audit time"):
        check(now=bad)


@pytest.mark.parametrize("bad", [0, 3601, True, 1.2])
def test_invalid_warning_budget(bad):
    with pytest.raises(ValueError, match="warning budget"):
        check(queue_warning_seconds=bad)


def test_bounds_reject_oversized_population():
    with pytest.raises(ValueError, match="bounded"):
        check(records=[None] * 1001, expected=[])


def test_does_not_mutate_input():
    row = state()
    before = copy.deepcopy(row)
    check(row)
    assert row == before


def test_expired_uncertain_claim_is_counted_once_in_warning_keys():
    result = check(state("IN_FLIGHT_UNCERTAIN", expiresAt=150), now=160)
    assert result["counts"]["IN_FLIGHT_UNCERTAIN"] == 1
    assert result["counts"]["EXPIRED_IN_FLIGHT_UNCERTAIN"] == 1
    assert result["counts"]["UNCERTAIN_DELAY_WARNING"] == 1
    assert result["warningKeys"] == [["s1", "f1"]]
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["maySendNotification"] is False


@pytest.mark.parametrize("ack_at", [300, 301])
def test_self_attested_ack_at_or_after_expiry_requires_review(ack_at):
    result = check(state("ACK_RECORDED_UNVERIFIED", ackAt=ack_at), now=400)
    assert result["counts"]["ACK_RECORDED_UNVERIFIED"] == 1
    assert result["counts"]["ACK_AT_OR_AFTER_EXPIRY_WARNING"] == 1
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["warningKeys"] == [["s1", "f1"]]
    assert result["providerDeliveryVerified"] is False
    assert result["recipientDeliveryVerified"] is False


def test_ack_before_expiry_does_not_trigger_late_warning():
    result = check(state("ACK_RECORDED_UNVERIFIED", ackAt=299), now=400)
    assert result["counts"]["ACK_AT_OR_AFTER_EXPIRY_WARNING"] == 0
    assert result["status"] == "DECLARED_ONLY"
    assert result["warningKeys"] == []


def test_short_lived_queue_warns_before_age_sla():
    # At 30s old the default 60s queue-age SLA has not fired.
    result = check(state(expiresAt=180), now=150)
    assert result["counts"]["QUEUE_DELAY_WARNING"] == 0
    assert result["counts"]["EXPIRING_SOON_WARNING"] == 1
    assert result["counts"]["EXPIRED_UNCLAIMED"] == 0
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["warningKeys"] == [["s1", "f1"]]
    assert result["maySendNotification"] is False


def test_expiry_warning_boundary_and_override():
    row = state(expiresAt=180)
    assert check(row, now=149)["counts"]["EXPIRING_SOON_WARNING"] == 0
    assert check(row, now=150)["counts"]["EXPIRING_SOON_WARNING"] == 1
    assert check(row, now=150, expiry_warning_seconds=29)["counts"]["EXPIRING_SOON_WARNING"] == 0
    assert check(row, now=179, expiry_warning_seconds=1)["counts"]["EXPIRING_SOON_WARNING"] == 1


def test_approaching_expiry_and_queue_delay_have_single_warning_identity():
    result = check(state(expiresAt=181), now=180)
    assert result["counts"]["QUEUE_DELAY_WARNING"] == 1
    assert result["counts"]["EXPIRING_SOON_WARNING"] == 1
    assert result["warningKeys"] == [["s1", "f1"]]


@pytest.mark.parametrize("bad", [0, 3601, True, 1.2, None])
def test_invalid_expiry_warning_budget_fails_closed(bad):
    with pytest.raises(ValueError, match="warning budget"):
        check(expiry_warning_seconds=bad)


@pytest.mark.parametrize("changes,now", [
    ({"expiresAt": 301}, 150),  # Target horizon=3 closes at 300.
    ({"baseStart": 61}, 150),  # Base must align to the feed timeframe.
    ({"issuedAt": 119}, 150),  # Cannot issue before completed base.
    ({"issuedAt": 180}, 200),  # Cannot issue after next candle closes.
])
def test_impossible_target_expiry_or_issue_timing_fails_closed(changes, now):
    with pytest.raises(ValueError, match="Invalid alert health state"):
        check(state(**changes), now=now)


def test_exact_target_completion_expiry_is_valid_but_not_authoritative():
    result = check(state(expiresAt=300), now=150)
    assert result["status"] == "DECLARED_ONLY"
    assert result["maySendNotification"] is False
    assert result["providerDeliveryVerified"] is False
