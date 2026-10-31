"""Invented monetary fixtures only; no market data, broker or orders."""
import copy
import random
from decimal import Decimal

import pytest

from app.development_cost_stress import audit_development_cost_stress
from test_development_candidate_census import fixture


def inputs():
    base = fixture()
    archives, _, _, _, _, _, trials, selection = base
    receipts = []
    for t in trials:
        is_b = t["candidateId"] == "B"
        receipts.append({
            "candidateId": t["candidateId"], "foldId": t["foldId"],
            "sourceSha256": t["sourceSha256"], "testSetSha256": t["testSetSha256"],
            "provider": archives[0]["provider"], "venue": archives[0]["venue"],
            "instrument": archives[0]["instrument"], "accountAlias": "demo_01",
            "currency": "GBP", "statementSha256": "d" * 64,
            "recordedAt": t["observedAt"] + 1,
            "grossPnl": "120" if is_b else "100",
            "spreadCost": "10" if is_b else "5",
            "slippageCost": "10" if is_b else "5",
            "commissionCost": "2", "financingCost": "1", "fxConversionCost": "1",
        })
    stresses = [{"id": "adverse_spread_slip", "spreadMultiplier": "3",
                 "slippageMultiplier": "3", "commissionMultiplier": "1",
                 "financingMultiplier": "1", "fxMultiplier": "1"}]
    assert max(r["recordedAt"] for r in receipts) <= selection["selectedAt"]
    return base + [receipts, stresses]


def audit(*args):
    return audit_development_cost_stress(*args)


def test_net_cost_winner_reverses_under_adverse_execution():
    result = audit(*inputs())
    baseline = result["scenarios"]["baseline"]
    adverse = result["scenarios"]["adverse_spread_slip"]
    assert baseline["declaredNetPnlByCandidate"] == {"A": "172", "B": "192"}
    assert adverse["declaredNetPnlByCandidate"] == {"A": "132", "B": "112"}
    assert baseline["diagnosticBestNetCandidateId"] == "B"
    assert adverse["diagnosticBestNetCandidateId"] == "A"
    assert result["selectedCandidateNetWinnerUnderEveryStress"] is False
    assert result["validationHoldoutAccess"] is False
    assert result["profitabilityEstablished"] is False
    assert result["mayExecuteLiveOrder"] is False
    assert result["mayExecutePaperOrder"] is False
    assert result["costReceiptsAuthenticated"] is False


def test_financing_credit_is_reduced_under_adverse_stress():
    args = inputs()
    for r in args[-2]:
        r["financingCost"] = "-4"
    args[-1][0]["financingMultiplier"] = "2"
    out = audit(*args)
    for cid in ("A", "B"):
        baseline = Decimal(out["scenarios"]["baseline"]["declaredNetPnlByCandidate"][cid])
        adverse = Decimal(out["scenarios"]["adverse_spread_slip"]["declaredNetPnlByCandidate"][cid])
        assert adverse < baseline


def test_deterministic_receipt_and_inputs_unchanged():
    args = inputs()
    before = copy.deepcopy(args)
    first = audit(*args)
    assert args == before
    args[-2].reverse()
    args[-1].reverse()
    assert audit(*args) == first
    args[-2][0]["commissionCost"] = "3"
    assert audit(*args)["postOutcomeCostReceiptSha256"] != first["postOutcomeCostReceiptSha256"]


def test_untouched_holdout_metadata_never_affects_cost_result():
    args = inputs()
    first = audit(*args)
    args[1][4]["labelAvailableAt"] += 3600
    assert audit(*args) == first


@pytest.mark.parametrize("mutation", [
    lambda x: x[-2].pop(),
    lambda x: x[-2].append(copy.deepcopy(x[-2][0])),
    lambda x: x[-2][0].__setitem__("candidateId", "unknown"),
    lambda x: x[-2][0].__setitem__("sourceSha256", "e" * 64),
    lambda x: x[-2][0].__setitem__("testSetSha256", "f" * 64),
    lambda x: x[-2][0].__setitem__("provider", "other"),
    lambda x: x[-2][0].__setitem__("venue", "other"),
    lambda x: x[-2][0].__setitem__("instrument", "WTIUSD"),
    lambda x: x[-2][0].__setitem__("accountAlias", "different"),
    lambda x: x[-2][0].__setitem__("currency", "USD"),
    lambda x: x[-2][0].__setitem__("statementSha256", "wrong"),
    lambda x: x[-2][0].__setitem__("recordedAt", x[6][0]["observedAt"] - 1),
    lambda x: x[-2][0].__setitem__("recordedAt", x[7]["selectedAt"] + 1),
    lambda x: x[-2][0].__setitem__("recordedAt", True),
    lambda x: x[-2][0].__setitem__("grossPnl", "NaN"),
    lambda x: x[-2][0].__setitem__("grossPnl", "1e9"),
    lambda x: x[-2][0].__setitem__("grossPnl", 100.0),
    lambda x: x[-2][0].__setitem__("grossPnl", "1000000001"),
    lambda x: x[-2][0].__setitem__("spreadCost", "-1"),
    lambda x: x[-2][0].__setitem__("slippageCost", "-1"),
    lambda x: x[-2][0].__setitem__("commissionCost", "-1"),
    lambda x: x[-2][0].__setitem__("fxConversionCost", "-1"),
    lambda x: x[-2][0].__setitem__("spreadCost", "0.0000001"),
    lambda x: x[-2][0].__setitem__("surprise", "true"),
    lambda x: x[-1][0].__setitem__("id", "baseline"),
    lambda x: x[-1][0].__setitem__("spreadMultiplier", "0.9"),
    lambda x: x[-1][0].__setitem__("spreadMultiplier", "NaN"),
    lambda x: x[-1][0].__setitem__("spreadMultiplier", 3),
    lambda x: x[-1][0].__setitem__("slippageMultiplier", "11"),
    lambda x: x[-1][0].__setitem__("slippageMultiplier", "1.00001"),
    lambda x: x[-1][0].update(spreadMultiplier="1", slippageMultiplier="1"),
    lambda x: x[-1][0].__setitem__("financingMultiplier", "0"),
    lambda x: x[-1][0].__setitem__("unknown", "1"),
    lambda x: x[6][0].__setitem__("score", "NaN"),
    lambda x: x[3][0].__setitem__("testEnd", x[2]["holdoutEnd"]),
])
def test_invalid_cost_evidence_or_upstream_census_fails_closed(mutation):
    args = inputs()
    mutation(args)
    with pytest.raises(ValueError):
        audit(*args)


def test_missing_stress_and_duplicate_stress_rejected():
    args = inputs()
    args[-1].clear()
    with pytest.raises(ValueError):
        audit(*args)
    args = inputs()
    args[-1].append(copy.deepcopy(args[-1][0]))
    with pytest.raises(ValueError):
        audit(*args)


def test_randomized_adverse_stress_never_improves_declared_net():
    rng = random.Random(20261026)
    for _ in range(200):
        args = inputs()
        for row in args[-2]:
            row["grossPnl"] = str(rng.randint(-1000, 1000))
            for field in ("spreadCost", "slippageCost", "commissionCost", "fxConversionCost"):
                row[field] = str(rng.randint(0, 100))
            row["financingCost"] = str(rng.randint(-100, 100))
        for field in ("spreadMultiplier", "slippageMultiplier", "commissionMultiplier", "financingMultiplier", "fxMultiplier"):
            args[-1][0][field] = str(rng.randint(2, 10))
        result = audit(*args)
        for cid in ("A", "B"):
            base = Decimal(result["scenarios"]["baseline"]["declaredNetPnlByCandidate"][cid])
            adverse = Decimal(result["scenarios"]["adverse_spread_slip"]["declaredNetPnlByCandidate"][cid])
            assert adverse <= base
