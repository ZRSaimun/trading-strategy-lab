"""Synthetic offline regression coverage; never a broker or profit test."""
import copy
import pytest
from app.financing_vintage_audit import audit_financing_vintages

SCOPE = {
    "provider": "Synthetic", "venue": "DEMO", "instrument": "XAUUSD-CFD",
    "account_alias": "paper-1", "position_id": "pos-1", "settlement_currency": "GBP",
    "opened_at": 100, "closed_at": 500, "audit_asof": 900,
    "required_rollovers": [200, 300, 400],
}


def v(id, rollover, revision, amount, published=None, ingested=None, **overrides):
    published = rollover + 5 if published is None else published
    ingested = published + 5 if ingested is None else ingested
    return dict(receipt_id=id, provider="Synthetic", venue="DEMO", instrument="XAUUSD-CFD",
                account_alias="paper-1", position_id="pos-1", settlement_currency="GBP",
                rollover_at=rollover, revision=revision, published_at=published,
                ingested_at=ingested, statement_sha256="a" * 64,
                amount_currency=amount, **overrides)


ROWS = [v("a", 200, 1, "1.20"), v("b", 300, 1, "-0.05"), v("c", 400, 1, "0.30")]


def run(scope=None, versions=None, cutoffs=None):
    return audit_financing_vintages(SCOPE if scope is None else scope,
                                    ROWS if versions is None else versions,
                                    [150, 250, 350, 450, 700] if cutoffs is None else cutoffs)


def test_asof_before_due_rollover_withholds_zero_claim():
    a = run()
    assert a["snapshots"][0]["status"] == "NO_DUE_DECLARED_ROLLOVERS"
    assert a["snapshots"][0]["total_charge_currency"] is None
    assert [s["total_charge_currency"] for s in a["snapshots"]] == [None, "1.20", "1.15", "1.45", "1.45"]
    assert not a["may_execute_order"] and not a["source_authenticated"]


def test_correction_visible_only_after_ingestion():
    correction = v("a2", 200, 2, "2.50", published=550, ingested=650)
    a = run(versions=ROWS + [correction])
    assert a["snapshots"][3]["total_charge_currency"] == "1.45"
    assert a["snapshots"][4]["total_charge_currency"] == "2.75"
    assert a["snapshots"][4]["selected_revisions"][0]["revision"] == 2


def test_late_initial_receipt_never_backfills_old_snapshot():
    late = v("a", 200, 1, "1.20", published=550, ingested=650)
    a = run(versions=[late, *ROWS[1:]])
    assert a["snapshots"][3]["status"] == "WITHHELD_MISSING_RECEIPTS"
    assert a["snapshots"][3]["total_charge_currency"] is None
    assert a["snapshots"][4]["status"] == "MATCHED_SELF_DECLARED"


def test_missing_receipt_withholds_entire_total():
    a = run(versions=ROWS[:-1])
    assert a["snapshots"][3]["missing_rollovers"] == [400]
    assert a["snapshots"][4]["total_charge_currency"] is None


def test_explicit_zero_is_not_omission():
    a = run(versions=[v("a", 200, 1, "0"), *ROWS[1:]])
    assert a["snapshots"][1]["total_charge_currency"] == "0.00"


def test_order_independence_nonmutation_and_diagnostic_hash():
    before = copy.deepcopy(ROWS)
    a = run(versions=ROWS)
    b = run(versions=list(reversed(ROWS)))
    assert a == b and ROWS == before
    assert len(a["declaration_sha256"]) == 64


def test_hash_changes_when_amount_or_ingestion_changes():
    a = run()["declaration_sha256"]
    for change in ({"amount_currency": "1.21"}, {"ingested_at": 250}, {"statement_sha256": "b"*64}):
        changed = [dict(ROWS[0], **change), *ROWS[1:]]
        assert run(versions=changed)["declaration_sha256"] != a


@pytest.mark.parametrize("bad", ["1e2", "NaN", "Infinity", "0.001", "-0", "-0.00", "+1", "01", "1000000000", "1,000"])
def test_invalid_amount_rejected(bad):
    with pytest.raises(ValueError, match="amount"):
        run(versions=[v("a", 200, 1, bad), *ROWS[1:]])


@pytest.mark.parametrize("scope", [
    dict(SCOPE, required_rollovers=[300, 200]),
    dict(SCOPE, required_rollovers=[200, 200]),
    dict(SCOPE, required_rollovers=[200, 500]),
    dict(SCOPE, required_rollovers=[True]),
    dict(SCOPE, opened_at=500),
    dict(SCOPE, audit_asof=400),
    dict(SCOPE, provider="Synthetic/foreign"),
    dict(SCOPE, unknown_field=True),
])
def test_invalid_scope_rejected(scope):
    with pytest.raises(ValueError):
        run(scope=scope)


@pytest.mark.parametrize("cutoffs", [[], [150, 150], [350, 150], [99], [901], [True], [1.5]])
def test_invalid_cutoffs_rejected(cutoffs):
    with pytest.raises(ValueError, match="cutoff"):
        run(cutoffs=cutoffs)


def test_duplicate_receipt_id_rejected_even_different_rollovers():
    with pytest.raises(ValueError, match="Duplicate"):
        run(versions=[ROWS[0], dict(ROWS[1], receipt_id="a"), ROWS[2]])


@pytest.mark.parametrize("change", [
    {"revision": 2}, {"revision": True}, {"rollover_at": 250},
    {"published_at": 199}, {"ingested_at": 204}, {"ingested_at": 901},
    {"statement_sha256": "A"*64}, {"provider": "Other"},
    {"settlement_currency": "USD"}, {"position_id": "foreign"},
    {"extra": 1},
])
def test_invalid_revision_rejected(change):
    with pytest.raises(ValueError):
        run(versions=[dict(ROWS[0], **change), *ROWS[1:]])


def test_gap_and_conflicting_revision_clocks_rejected():
    for revision in [1, 3]:
        with pytest.raises(ValueError, match="revision sequence"):
            run(versions=[*ROWS, v("a2", 200, revision, "2.00", published=550, ingested=600)])
    with pytest.raises(ValueError, match="Nonmonotonic"):
        run(versions=[*ROWS, v("a2", 200, 2, "2.00", published=205, ingested=650)])
    with pytest.raises(ValueError, match="Nonmonotonic"):
        run(versions=[*ROWS, v("a2", 200, 2, "2.00", published=206, ingested=209)])


def test_empty_declared_schedule_cannot_claim_free_financing():
    a = run(scope=dict(SCOPE, required_rollovers=[]), versions=[])
    assert all(s["total_charge_currency"] is None for s in a["snapshots"])


def test_no_fabricated_broker_authentication_or_profit():
    a = run()
    assert a["coverage"] == "SELF_DECLARED_ONLY_NOT_BROKER_AUTHENTICATED"
    assert a["calendar_complete_verified"] is False
    assert a["realized_net_cost_verified"] is False
    assert a["verified_profitability"] is False
    assert a["may_execute_order"] is False


def test_synthetic_multi_year_financing_identity_and_missing_year_withheld():
    from datetime import datetime, timezone
    rollovers = [int(datetime(y, 1, 10, tzinfo=timezone.utc).timestamp()) for y in range(2019, 2027)]
    scope = dict(SCOPE, opened_at=rollovers[0]-100, closed_at=rollovers[-1]+100,
                 audit_asof=rollovers[-1]+500, required_rollovers=rollovers)
    receipts = [v(f"r-{y}", t, 1, "0.01", published=t+1, ingested=t+2)
                for y,t in zip(range(2019, 2027), rollovers)]
    report = run(scope=scope, versions=receipts, cutoffs=[rollovers[0]+10, rollovers[-1]+10])
    assert [x["total_charge_currency"] for x in report["snapshots"]] == ["0.01", "0.08"]
    missing = run(scope=scope, versions=receipts[:-1], cutoffs=[rollovers[-1]+10])
    assert missing["snapshots"][0]["total_charge_currency"] is None
    assert missing["snapshots"][0]["missing_rollovers"] == [rollovers[-1]]


def test_rejects_cross_position_even_if_rollover_time_and_amount_match():
    for field, value in (("account_alias", "other"), ("venue", "LIVE"),
                         ("instrument", "XAGUSD-CFD")):
        with pytest.raises(ValueError, match="Cross-source"):
            run(versions=[dict(ROWS[0], **{field: value}), *ROWS[1:]])
