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
    assert result["warningKeys"] == [["s1", "f1"]]
    assert result["maySendNotification"] is False


def test_fresh_uncertain_claim_is_actionable_before_delay_threshold():
    result = check(state("IN_FLIGHT_UNCERTAIN"), now=130)
    assert result["counts"]["UNCERTAIN_DELAY_WARNING"] == 0
    assert result["counts"]["EXPIRED_IN_FLIGHT_UNCERTAIN"] == 0
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert result["warningKeys"] == [["s1", "f1"]]
    assert result["maySendNotification"] is False


def test_fresh_uncertain_review_keys_are_sorted_and_deduplicated():
    records = [
        {"sessionId": "s2", "state": state("IN_FLIGHT_UNCERTAIN", forecastId="f2", claimId="b" * 32)},
        {"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN")},
        {"sessionId": "s1", "state": state(forecastId="f3")},
    ]
    expected = [("s1", "f3"), ("s2", "f2"), ("s1", "f1")]
    result = check(records=records, expected=expected, now=130)
    assert result["counts"]["IN_FLIGHT_UNCERTAIN"] == 2
    assert result["counts"]["UNCERTAIN_DELAY_WARNING"] == 0
    assert result["warningKeys"] == [["s1", "f1"], ["s2", "f2"]]
    assert result["status"] == "OPERATOR_REVIEW_REQUIRED"


def test_old_uncertain_claim_warning():
    result = check(state("IN_FLIGHT_UNCERTAIN"), now=160)
    assert result["oldestUncertainSeconds"] == 30
    assert result["counts"]["UNCERTAIN_DELAY_WARNING"] == 1


def test_ack_never_counts_as_human_delivery():
    result = check(state("ACK_RECORDED_UNVERIFIED"))
    assert result["counts"]["ACK_RECORDED_UNVERIFIED"] == 1
    assert result["maxSelfAttestedAckLagSeconds"] == 10
    assert result["unverifiedAckKeys"] == [["s1", "f1"]]
    assert result["warningKeys"] == []
    assert result["status"] == "DECLARED_ONLY"
    assert result["providerDeliveryVerified"] is False
    assert result["recipientDeliveryVerified"] is False




def test_unverified_ack_reconciliation_inventory_is_sorted_and_separate_from_warnings():
    records = [
        {"sessionId": "s2", "state": state("ACK_RECORDED_UNVERIFIED", forecastId="f2", claimId="b" * 32)},
        {"sessionId": "s1", "state": state("QUEUED", forecastId="f3")},
        {"sessionId": "s1", "state": state("ACK_RECORDED_UNVERIFIED")},
    ]
    expected = [("s1", "f1"), ("s2", "f2"), ("s1", "f3")]
    result = check(records=records, expected=expected, now=150)
    assert result["unverifiedAckKeys"] == [["s1", "f1"], ["s2", "f2"]]
    assert result["counts"]["ACK_RECORDED_UNVERIFIED"] == len(result["unverifiedAckKeys"])
    assert result["warningKeys"] == []
    assert result["status"] == "DECLARED_ONLY"
    assert result["recipientDeliveryVerified"] is False
    assert check(records=list(reversed(records)), expected=list(reversed(expected)), now=150) == result


def test_unverified_ack_inventory_is_empty_without_ack_states():
    result = check(records=[{"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN")}], now=150)
    assert result["unverifiedAckKeys"] == []
    assert result["warningKeys"] == [["s1", "f1"]]

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
    assert result["unverifiedAckKeys"] == [["s1", "f1"]]
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


def test_warning_reasons_reconcile_overlapping_queue_and_uncertain_incidents():
    queued = check(state(expiresAt=181), now=180)
    assert queued["warningKeys"] == [["s1", "f1"]]
    assert queued["warningReasons"] == [{"key": ["s1", "f1"], "reasons":
        ["EXPIRING_SOON_WARNING", "QUEUE_DELAY_WARNING"]}]
    uncertain = check(state("IN_FLIGHT_UNCERTAIN", expiresAt=150), now=160)
    assert uncertain["warningReasons"] == [{"key": ["s1", "f1"], "reasons":
        ["EXPIRED_IN_FLIGHT_UNCERTAIN", "IN_FLIGHT_UNCERTAIN", "UNCERTAIN_DELAY_WARNING"]}]
    assert uncertain["maySendNotification"] is False


def test_warning_reasons_distinguish_expired_queue_and_late_ack():
    expired = check(state(), now=300)
    assert expired["warningReasons"] == [{"key": ["s1", "f1"], "reasons": ["EXPIRED_UNCLAIMED"]}]
    late = check(state("ACK_RECORDED_UNVERIFIED", ackAt=300), now=400)
    assert late["warningReasons"] == [{"key": ["s1", "f1"],
        "reasons": ["ACK_AT_OR_AFTER_EXPIRY_WARNING"]}]
    assert late["unverifiedAckKeys"] == [["s1", "f1"]]
    assert check()["warningReasons"] == []


def test_warning_reasons_are_stable_across_input_order_and_disjoint_from_timeline_acks():
    records = [
        {"sessionId": "s2", "state": state("ACK_RECORDED_UNVERIFIED", forecastId="f3", claimId="b" * 32)},
        {"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN", forecastId="f2")},
        {"sessionId": "s1", "state": state(expiresAt=180)},
    ]
    expected = [("s1", "f1"), ("s1", "f2"), ("s2", "f3")]
    a = check(records=records, expected=expected, now=150)
    b = check(records=list(reversed(records)), expected=list(reversed(expected)), now=150)
    assert a == b
    assert a["warningKeys"] == [item["key"] for item in a["warningReasons"]]
    assert a["warningReasons"] == [
        {"key": ["s1", "f1"], "reasons": ["EXPIRING_SOON_WARNING"]},
        {"key": ["s1", "f2"], "reasons": ["IN_FLIGHT_UNCERTAIN"]},
    ]
    assert a["unverifiedAckKeys"] == [["s2", "f3"]]
    assert a["recipientDeliveryVerified"] is False


def test_reused_claim_token_across_sessions_fails_closed():
    records = [
        {"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN")},
        {"sessionId": "s2", "state": state("IN_FLIGHT_UNCERTAIN", forecastId="f2")},
    ]
    with pytest.raises(ValueError, match="Reused forecast alert claim ID"):
        check(records=records, expected=[("s1", "f1"), ("s2", "f2")])


def test_reused_claim_token_across_ack_and_uncertain_fails_closed():
    records = [
        {"sessionId": "s1", "state": state("ACK_RECORDED_UNVERIFIED")},
        {"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN", forecastId="f2")},
    ]
    with pytest.raises(ValueError, match="Reused forecast alert claim ID"):
        check(records=records, expected=[("s1", "f1"), ("s1", "f2")])


def test_distinct_claim_tokens_and_unclaimed_rows_remain_valid_and_order_independent():
    records = [
        {"sessionId": "s2", "state": state("ACK_RECORDED_UNVERIFIED",
                                          forecastId="f2", claimId="b" * 32)},
        {"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN")},
        {"sessionId": "s3", "state": state("CANCELLED", forecastId="f3")},
        {"sessionId": "s4", "state": state("QUEUED", forecastId="f4")},
    ]
    expected = [("s1", "f1"), ("s2", "f2"), ("s3", "f3"), ("s4", "f4")]
    result = check(records=records, expected=expected, now=150)
    assert result == check(records=list(reversed(records)),
                           expected=list(reversed(expected)), now=150)
    assert result["counts"]["IN_FLIGHT_UNCERTAIN"] == 1
    assert result["counts"]["ACK_RECORDED_UNVERIFIED"] == 1
    assert result["counts"]["CANCELLED"] == 1
    assert result["counts"]["QUEUED"] == 1
    assert result["maySendNotification"] is False
    assert result["mayExecutePaperOrder"] is False
    assert result["mayExecuteLiveOrder"] is False



def test_unverified_ack_escalates_after_reconciliation_budget_without_retry_authority():
    row = state("ACK_RECORDED_UNVERIFIED")
    before = check(row, now=439)
    assert before["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 0
    assert before["status"] == "DECLARED_ONLY"
    assert before["unverifiedAckKeys"] == [["s1", "f1"]]
    assert before["oldestUnverifiedAckAgeSeconds"] == 299
    at = check(row, now=440)
    assert at["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 1
    assert at["status"] == "OPERATOR_REVIEW_REQUIRED"
    assert at["warningKeys"] == [["s1", "f1"]]
    assert at["warningReasons"] == [{"key": ["s1", "f1"],
        "reasons": ["ACK_RECONCILIATION_OVERDUE_WARNING"]}]
    assert at["oldestUnverifiedAckAgeSeconds"] == 300
    assert at["recipientDeliveryVerified"] is False
    assert at["maySendNotification"] is False
    assert at["mayExecutePaperOrder"] is False
    assert at["mayExecuteLiveOrder"] is False


def test_ack_reconciliation_budget_override_and_empty_inventory():
    row = state("ACK_RECORDED_UNVERIFIED")
    assert check(row, now=150, unverified_ack_warning_seconds=10)["counts"][
        "ACK_RECONCILIATION_OVERDUE_WARNING"] == 1
    assert check(row, now=150, unverified_ack_warning_seconds=11)["counts"][
        "ACK_RECONCILIATION_OVERDUE_WARNING"] == 0
    empty = check(records=[], expected=[], now=450)
    assert empty["oldestUnverifiedAckAgeSeconds"] == 0
    assert empty["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 0


@pytest.mark.parametrize("bad", [0, 3601, True, 1.5, None])
def test_invalid_ack_reconciliation_warning_budget_fails_closed(bad):
    with pytest.raises(ValueError, match="warning budget"):
        check(unverified_ack_warning_seconds=bad)


def test_ack_reconciliation_warning_order_independent_and_overlaps_late_ack():
    records = [
        {"sessionId": "s2", "state": state("ACK_RECORDED_UNVERIFIED",
            forecastId="f2", claimId="b" * 32, ackAt=300)},
        {"sessionId": "s1", "state": state("ACK_RECORDED_UNVERIFIED")},
    ]
    expected = [("s1", "f1"), ("s2", "f2")]
    a = check(records=records, expected=expected, now=650)
    b = check(records=list(reversed(records)), expected=list(reversed(expected)), now=650)
    assert a == b
    assert a["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 2
    assert a["counts"]["ACK_AT_OR_AFTER_EXPIRY_WARNING"] == 1
    assert a["warningReasons"] == [
        {"key": ["s1", "f1"], "reasons": ["ACK_RECONCILIATION_OVERDUE_WARNING"]},
        {"key": ["s2", "f2"], "reasons": [
            "ACK_AT_OR_AFTER_EXPIRY_WARNING", "ACK_RECONCILIATION_OVERDUE_WARNING"]},
    ]
    assert a["unverifiedAckKeys"] == [["s1", "f1"], ["s2", "f2"]]


def test_earliest_active_queue_expiry_countdown_ties_and_order_independence():
    records = [
        {"sessionId": "s2", "state": state(forecastId="f2", expiresAt=180)},
        {"sessionId": "s1", "state": state(forecastId="f1", expiresAt=180)},
        {"sessionId": "s1", "state": state(forecastId="f3", expiresAt=240)},
    ]
    expected = [("s1", "f3"), ("s2", "f2"), ("s1", "f1")]
    a = check(records=records, expected=expected, now=150)
    b = check(records=list(reversed(records)), expected=list(reversed(expected)), now=150)
    assert a == b
    assert a["earliestQueuedExpirySecondsRemaining"] == 30
    assert a["earliestQueuedExpiryKeys"] == [["s1", "f1"], ["s2", "f2"]]
    assert a["maySendNotification"] is False
    at = check(records=records, expected=expected, now=180)
    assert at["earliestQueuedExpirySecondsRemaining"] == 60
    assert at["earliestQueuedExpiryKeys"] == [["s1", "f3"]]
    assert at["counts"]["EXPIRED_UNCLAIMED"] == 2


def test_earliest_queue_expiry_exact_one_second_and_excludes_claims():
    queued = check(state(expiresAt=151), now=150)
    assert queued["earliestQueuedExpirySecondsRemaining"] == 1
    assert queued["earliestQueuedExpiryKeys"] == [["s1", "f1"]]
    expired = check(state(expiresAt=151), now=151)
    assert expired["earliestQueuedExpirySecondsRemaining"] is None
    assert expired["earliestQueuedExpiryKeys"] == []
    uncertain = check(state("IN_FLIGHT_UNCERTAIN"), now=150)
    assert uncertain["earliestQueuedExpirySecondsRemaining"] is None
    assert uncertain["earliestQueuedExpiryKeys"] == []


def test_earliest_queue_expiry_empty_and_cancelled_population():
    empty = check(records=[], expected=[])
    cancelled = check(state("CANCELLED"))
    for report in (empty, cancelled):
        assert report["earliestQueuedExpirySecondsRemaining"] is None
        assert report["earliestQueuedExpiryKeys"] == []
        assert report["mayExecutePaperOrder"] is False
        assert report["mayExecuteLiveOrder"] is False


def test_oldest_unverified_ack_keys_are_tied_and_order_independent():
    records = [
        {"sessionId": "s3", "state": state("ACK_RECORDED_UNVERIFIED",
            forecastId="f3", claimId="c" * 32, ackAt=180)},
        {"sessionId": "s2", "state": state("ACK_RECORDED_UNVERIFIED",
            forecastId="f2", claimId="b" * 32)},
        {"sessionId": "s1", "state": state("QUEUED", forecastId="f4")},
        {"sessionId": "s1", "state": state("ACK_RECORDED_UNVERIFIED")},
    ]
    expected = [("s1", "f1"), ("s1", "f4"), ("s2", "f2"), ("s3", "f3")]
    first = check(records=records, expected=expected, now=440)
    reversed_result = check(records=list(reversed(records)),
                            expected=list(reversed(expected)), now=440)
    assert first == reversed_result
    assert first["oldestUnverifiedAckAgeSeconds"] == 300
    assert first["oldestUnverifiedAckKeys"] == [["s1", "f1"], ["s2", "f2"]]
    assert first["unverifiedAckKeys"] == [["s1", "f1"], ["s2", "f2"], ["s3", "f3"]]
    assert first["maySendNotification"] is False
    assert first["mayExecuteLiveOrder"] is False


def test_oldest_unverified_ack_keys_empty_without_ack_population():
    for records, expected in (
        ([], []),
        ([{"sessionId": "s1", "state": state("IN_FLIGHT_UNCERTAIN")}],
         [("s1", "f1")]),
        ([{"sessionId": "s1", "state": state("CANCELLED")}],
         [("s1", "f1")]),
    ):
        result = check(records=records, expected=expected, now=150)
        assert result["oldestUnverifiedAckAgeSeconds"] == 0
        assert result["oldestUnverifiedAckKeys"] == []


def test_zero_age_ack_is_still_identified_for_reconciliation():
    result = check(state("ACK_RECORDED_UNVERIFIED"), now=140)
    assert result["oldestUnverifiedAckAgeSeconds"] == 0
    assert result["oldestUnverifiedAckKeys"] == [["s1", "f1"]]
    assert result["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 0
    assert result["recipientDeliveryVerified"] is False


def test_next_unverified_ack_escalation_selects_earliest_unbreached_deadline():
    records = [
        {"sessionId": "s2", "state": state("ACK_RECORDED_UNVERIFIED",
            forecastId="f2", claimId="b" * 32, ackAt=145)},
        {"sessionId": "s3", "state": state("ACK_RECORDED_UNVERIFIED",
            forecastId="f3", claimId="c" * 32, ackAt=130)},
        {"sessionId": "s1", "state": state("ACK_RECORDED_UNVERIFIED", ackAt=140)},
        {"sessionId": "s4", "state": state("ACK_RECORDED_UNVERIFIED",
            forecastId="f4", claimId="d" * 32, ackAt=140)},
    ]
    expected = [("s1", "f1"), ("s2", "f2"), ("s3", "f3"), ("s4", "f4")]
    result = check(records=records, expected=expected, now=160,
                   unverified_ack_warning_seconds=30)
    assert result["nextUnverifiedAckEscalationSecondsRemaining"] == 10
    assert result["nextUnverifiedAckEscalationKeys"] == [["s1", "f1"], ["s4", "f4"]]
    assert result["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 1
    assert result["warningKeys"] == [["s3", "f3"]]
    assert check(records=list(reversed(records)), expected=list(reversed(expected)),
                 now=160, unverified_ack_warning_seconds=30) == result


def test_next_unverified_ack_escalation_excludes_exact_breach_and_empty_cohort():
    overdue = check(state("ACK_RECORDED_UNVERIFIED"), now=170,
                    unverified_ack_warning_seconds=30)
    assert overdue["nextUnverifiedAckEscalationSecondsRemaining"] is None
    assert overdue["nextUnverifiedAckEscalationKeys"] == []
    assert overdue["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 1
    empty = check(state("QUEUED"), now=150)
    assert empty["nextUnverifiedAckEscalationSecondsRemaining"] is None
    assert empty["nextUnverifiedAckEscalationKeys"] == []


def test_next_unverified_ack_escalation_exactly_one_second_remaining():
    result = check(state("ACK_RECORDED_UNVERIFIED"), now=169,
                   unverified_ack_warning_seconds=30)
    assert result["nextUnverifiedAckEscalationSecondsRemaining"] == 1
    assert result["nextUnverifiedAckEscalationKeys"] == [["s1", "f1"]]
    assert result["counts"]["ACK_RECONCILIATION_OVERDUE_WARNING"] == 0


def test_next_queue_delay_warning_ties_and_mixed_statuses_are_order_independent():
    records = [
        {"sessionId": "s4", "state": state(forecastId="f4", issuedAt=130)},
        {"sessionId": "s3", "state": state(forecastId="f3", issuedAt=130)},
        {"sessionId": "s2", "state": state(forecastId="f2", issuedAt=140)},
        {"sessionId": "s1", "state": state(forecastId="f1")},
        {"sessionId": "s5", "state": state(forecastId="f5", expiresAt=150)},
        {"sessionId": "s6", "state": state("IN_FLIGHT_UNCERTAIN", forecastId="f6")},
        {"sessionId": "s7", "state": state("ACK_RECORDED_UNVERIFIED",
                                          forecastId="f7", claimId="b" * 32)},
        {"sessionId": "s8", "state": state("CANCELLED", forecastId="f8")},
    ]
    expected = [(row["sessionId"], row["state"]["forecastId"]) for row in records]
    result = check(records=records, expected=expected, now=150,
                   queue_warning_seconds=30)
    assert result == check(records=list(reversed(records)),
                           expected=list(reversed(expected)), now=150,
                           queue_warning_seconds=30)
    assert result["nextQueueDelayWarningSecondsRemaining"] == 10
    assert result["nextQueueDelayWarningKeys"] == [["s3", "f3"], ["s4", "f4"]]
    assert result["counts"]["QUEUE_DELAY_WARNING"] == 1
    assert result["counts"]["EXPIRED_UNCLAIMED"] == 1
    assert result["counts"]["IN_FLIGHT_UNCERTAIN"] == 1
    assert result["maySendNotification"] is False
    assert result["mayExecuteLiveOrder"] is False


def test_next_queue_delay_warning_exact_boundary_and_empty_cohorts():
    one_second = check(now=179)
    assert one_second["nextQueueDelayWarningSecondsRemaining"] == 1
    assert one_second["nextQueueDelayWarningKeys"] == [["s1", "f1"]]
    at_warning = check(now=180)
    assert at_warning["nextQueueDelayWarningSecondsRemaining"] is None
    assert at_warning["nextQueueDelayWarningKeys"] == []
    assert at_warning["counts"]["QUEUE_DELAY_WARNING"] == 1
    expired = check(now=300)
    assert expired["nextQueueDelayWarningSecondsRemaining"] is None
    assert expired["nextQueueDelayWarningKeys"] == []
    for report in (
        check(records=[], expected=[]),
        check(state("CANCELLED")),
        check(state("IN_FLIGHT_UNCERTAIN")),
        check(state("ACK_RECORDED_UNVERIFIED")),
    ):
        assert report["nextQueueDelayWarningSecondsRemaining"] is None
        assert report["nextQueueDelayWarningKeys"] == []


def test_next_queue_delay_warning_respects_override_and_expiry_overlap():
    before = check(state(expiresAt=165), now=150, queue_warning_seconds=45)
    # The alert expires at the exact queue-delay threshold: it can never
    # enter QUEUE_DELAY_WARNING while queued, so no future delay is advertised.
    assert before["nextQueueDelayWarningSecondsRemaining"] is None
    assert before["nextQueueDelayWarningKeys"] == []
    assert before["counts"]["EXPIRING_SOON_WARNING"] == 1
    assert before["counts"]["QUEUE_DELAY_WARNING"] == 0
    assert before["status"] == "OPERATOR_REVIEW_REQUIRED"
    at_expiry = check(state(expiresAt=165), now=165,
                      queue_warning_seconds=45)
    assert at_expiry["nextQueueDelayWarningSecondsRemaining"] is None
    assert at_expiry["nextQueueDelayWarningKeys"] == []
    assert at_expiry["counts"]["EXPIRED_UNCLAIMED"] == 1



def test_queue_delay_deadline_preempted_by_earlier_expiry():
    result = check(state(expiresAt=164), now=150, queue_warning_seconds=45)
    assert result["nextQueueDelayWarningSecondsRemaining"] is None
    assert result["nextQueueDelayWarningKeys"] == []
    assert result["earliestQueuedExpirySecondsRemaining"] == 14
    assert result["counts"]["EXPIRING_SOON_WARNING"] == 1
    at_expiry = check(state(expiresAt=164), now=164, queue_warning_seconds=45)
    assert at_expiry["counts"]["EXPIRED_UNCLAIMED"] == 1
    assert at_expiry["counts"]["QUEUE_DELAY_WARNING"] == 0
    assert at_expiry["nextQueueDelayWarningSecondsRemaining"] is None


def test_queue_delay_deadline_before_expiry_is_reachable():
    before = check(state(expiresAt=166), now=150, queue_warning_seconds=45)
    assert before["nextQueueDelayWarningSecondsRemaining"] == 15
    assert before["nextQueueDelayWarningKeys"] == [["s1", "f1"]]
    at_warning = check(state(expiresAt=166), now=165, queue_warning_seconds=45)
    assert at_warning["counts"]["QUEUE_DELAY_WARNING"] == 1
    assert at_warning["counts"]["EXPIRED_UNCLAIMED"] == 0
    assert at_warning["nextQueueDelayWarningSecondsRemaining"] is None
    assert at_warning["maySendNotification"] is False


def test_queue_delay_deadline_ignores_unreachable_earlier_candidate():
    records = [
        {"sessionId": "s3", "state": state(forecastId="f3", issuedAt=130, expiresAt=190)},
        {"sessionId": "s1", "state": state(forecastId="f1", issuedAt=120, expiresAt=160)},
        {"sessionId": "s2", "state": state(forecastId="f2", issuedAt=120, expiresAt=190)},
    ]
    expected = [("s1", "f1"), ("s2", "f2"), ("s3", "f3")]
    report = check(records=records, expected=expected, now=150,
                   queue_warning_seconds=50)
    assert report["nextQueueDelayWarningSecondsRemaining"] == 20
    assert report["nextQueueDelayWarningKeys"] == [["s2", "f2"]]
    assert report == check(records=list(reversed(records)),
                           expected=list(reversed(expected)), now=150,
                           queue_warning_seconds=50)
    assert report["mayExecutePaperOrder"] is False
    assert report["mayExecuteLiveOrder"] is False


def test_next_expiry_soon_warning_selects_nearest_ties_and_is_order_independent():
    records = [
        {"sessionId": "s3", "state": state(forecastId="f3", expiresAt=270)},
        {"sessionId": "s2", "state": state(forecastId="f2", expiresAt=240)},
        {"sessionId": "s1", "state": state(forecastId="f1", expiresAt=240)},
        {"sessionId": "s4", "state": state(forecastId="f4", expiresAt=150)},
        {"sessionId": "s5", "state": state("IN_FLIGHT_UNCERTAIN", forecastId="f5")},
        {"sessionId": "s6", "state": state("CANCELLED", forecastId="f6")},
    ]
    expected = [(row["sessionId"], row["state"]["forecastId"]) for row in records]
    result = check(records=records, expected=expected, now=150)
    assert result["nextExpirySoonWarningSecondsRemaining"] == 60
    assert result["nextExpirySoonWarningKeys"] == [["s1", "f1"], ["s2", "f2"]]
    assert result["earliestQueuedExpirySecondsRemaining"] == 90
    assert result["counts"]["EXPIRED_UNCLAIMED"] == 1
    assert result == check(records=list(reversed(records)),
                           expected=list(reversed(expected)), now=150)
    assert result["maySendNotification"] is False


def test_next_expiry_soon_warning_exact_boundary_and_expiry():
    before = check(state(expiresAt=240), now=209)
    assert before["nextExpirySoonWarningSecondsRemaining"] == 1
    assert before["nextExpirySoonWarningKeys"] == [["s1", "f1"]]
    assert before["counts"]["EXPIRING_SOON_WARNING"] == 0
    at = check(state(expiresAt=240), now=210)
    assert at["nextExpirySoonWarningSecondsRemaining"] is None
    assert at["nextExpirySoonWarningKeys"] == []
    assert at["counts"]["EXPIRING_SOON_WARNING"] == 1
    expired = check(state(expiresAt=240), now=240)
    assert expired["nextExpirySoonWarningSecondsRemaining"] is None
    assert expired["nextExpirySoonWarningKeys"] == []
    assert expired["counts"]["EXPIRED_UNCLAIMED"] == 1


def test_next_expiry_soon_warning_respects_budget_and_empty_cohorts():
    result = check(state(expiresAt=180), now=150, expiry_warning_seconds=1)
    assert result["nextExpirySoonWarningSecondsRemaining"] == 29
    assert result["nextExpirySoonWarningKeys"] == [["s1", "f1"]]
    at = check(state(expiresAt=180), now=179, expiry_warning_seconds=1)
    assert at["counts"]["EXPIRING_SOON_WARNING"] == 1
    assert at["nextExpirySoonWarningSecondsRemaining"] is None
    for report in (
        check(state(expiresAt=140), now=130),
        check(records=[], expected=[]),
        check(state("CANCELLED")),
        check(state("IN_FLIGHT_UNCERTAIN")),
        check(state("ACK_RECORDED_UNVERIFIED")),
    ):
        assert report["nextExpirySoonWarningSecondsRemaining"] is None
        assert report["nextExpirySoonWarningKeys"] == []
        assert report["mayExecutePaperOrder"] is False
        assert report["mayExecuteLiveOrder"] is False
