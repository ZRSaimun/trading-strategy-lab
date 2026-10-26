"""Fail-closed, development-only CFD cost stress over a validated candidate census.

All receipts, clocks, source identities and amounts are caller declarations. This
module never reads validation/holdout outcomes or calls a broker or order route.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
import re

from app.development_candidate_census import audit_development_candidate_census

_SHA = re.compile(r"[0-9a-f]{64}\Z")
_ALIAS = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MONEY = re.compile(r"-?(?:0|[1-9][0-9]{0,11})(?:\.[0-9]{1,6})?\Z")
_FACTOR = re.compile(r"(?:[1-9](?:\.[0-9]{1,4})?|10(?:\.0{1,4})?)\Z")
_RECEIPT_KEYS = frozenset({
    "candidateId", "foldId", "sourceSha256", "testSetSha256",
    "provider", "venue", "instrument", "accountAlias", "currency",
    "statementSha256", "recordedAt", "grossPnl", "spreadCost",
    "slippageCost", "commissionCost", "financingCost", "fxConversionCost",
})
_STRESS_KEYS = frozenset({
    "id", "spreadMultiplier", "slippageMultiplier", "commissionMultiplier",
    "financingMultiplier", "fxMultiplier",
})
_COST_FIELDS = ("spreadCost", "slippageCost", "commissionCost", "financingCost", "fxConversionCost")
_MAX_RECEIPTS = 6400
_MAX_STRESSES = 8


def _money(value, *, signed=False):
    if type(value) is not str or _MONEY.fullmatch(value) is None:
        raise ValueError("Malformed exact-decimal cash amount")
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("Malformed cash amount") from exc
    if abs(number) > Decimal("1000000000") or (not signed and number < 0):
        raise ValueError("Cash amount exceeds bound or has invalid sign")
    return number


def _factor(value):
    if type(value) is not str or _FACTOR.fullmatch(value) is None:
        raise ValueError("Invalid adverse-only stress multiplier")
    factor = Decimal(value)
    if not Decimal(1) <= factor <= Decimal(10):
        raise ValueError("Invalid adverse-only stress multiplier")
    return factor


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=True, allow_nan=False).encode("ascii")).hexdigest()


def _net(receipt, factors):
    gross = receipt["grossPnl"]
    costs = (
        receipt["spreadCost"] * factors["spreadMultiplier"]
        + receipt["slippageCost"] * factors["slippageMultiplier"]
        + receipt["commissionCost"] * factors["commissionMultiplier"]
        + receipt["fxConversionCost"] * factors["fxMultiplier"]
    )
    finance = receipt["financingCost"]
    # A financing credit is reduced, not enlarged, by adverse stress.
    costs += (finance * factors["financingMultiplier"] if finance >= 0
              else finance / factors["financingMultiplier"])
    return gross - costs, costs


def audit_development_cost_stress(
    archives, observations, protocol, folds, candidates, registration,
    trials, selection, receipts, stresses,
):
    """Revalidate source-isolated folds/candidate selection, then stress declared costs.

    The candidate selection uses the original *dimensionless* research score;
    monetary P&L here is a separate diagnostic, not a revised selection or a
    valid performance estimate. Explicit zero costs do not prove free trading.
    """
    census = audit_development_candidate_census(
        archives, observations, protocol, folds, candidates,
        registration, trials, selection,
    )
    if (type(receipts) is not list or len(receipts) != len(trials) or
            len(receipts) > _MAX_RECEIPTS or type(stresses) is not list or
            not 1 <= len(stresses) <= _MAX_STRESSES):
        raise ValueError("Incomplete or unbounded cost receipt/stress population")
    trial_map = {(t["candidateId"], t["foldId"]): t for t in trials}
    source = (archives[0]["provider"], archives[0]["venue"], archives[0]["instrument"])
    parsed, seen, account, currency = {}, set(), None, None
    for row in receipts:
        if type(row) is not dict or set(row) != _RECEIPT_KEYS:
            raise ValueError("Exact cost receipt schema required")
        key = (row["candidateId"], row["foldId"])
        if key not in trial_map or key in seen:
            raise ValueError("Missing, duplicate or undeclared candidate-fold receipt")
        seen.add(key)
        trial = trial_map[key]
        if (row["sourceSha256"] != trial["sourceSha256"] or
                row["testSetSha256"] != trial["testSetSha256"] or
                (row["provider"], row["venue"], row["instrument"]) != source):
            raise ValueError("Cost receipt source, test set or instrument mismatch")
        if (type(row["accountAlias"]) is not str or
                _ALIAS.fullmatch(row["accountAlias"]) is None or
                type(row["currency"]) is not str or
                re.fullmatch(r"[A-Z]{3}", row["currency"]) is None or
                type(row["statementSha256"]) is not str or
                _SHA.fullmatch(row["statementSha256"]) is None):
            raise ValueError("Invalid account/currency/statement identity")
        if account is None:
            account, currency = row["accountAlias"], row["currency"]
        if (row["accountAlias"], row["currency"]) != (account, currency):
            raise ValueError("Mixed account or settlement currency")
        if (type(row["recordedAt"]) is not int or
                not trial["observedAt"] <= row["recordedAt"] <= selection["selectedAt"]):
            raise ValueError("Cost evidence unavailable at selection or future-dated")
        parsed[key] = {field: _money(row[field], signed=field in ("grossPnl", "financingCost"))
                       for field in ("grossPnl",) + _COST_FIELDS}
    if seen != set(trial_map):
        raise ValueError("Incomplete declared candidate-fold cost census")

    stress_map = {}
    for row in stresses:
        if type(row) is not dict or set(row) != _STRESS_KEYS:
            raise ValueError("Exact adverse stress schema required")
        name = row["id"]
        if (type(name) is not str or _ALIAS.fullmatch(name) is None or
                name == "baseline" or name in stress_map):
            raise ValueError("Duplicate or invalid stress scenario")
        factors = {k: _factor(row[k]) for k in _STRESS_KEYS - {"id"}}
        if all(v == 1 for v in factors.values()):
            raise ValueError("Adverse stress must worsen at least one assumption")
        stress_map[name] = factors

    baseline = {k: Decimal(1) for k in _STRESS_KEYS - {"id"}}
    scenario_results = {}
    for name, factors in [("baseline", baseline)] + sorted(stress_map.items()):
        totals = {c["id"]: Decimal(0) for c in candidates}
        costs = {c["id"]: Decimal(0) for c in candidates}
        negative_folds = {c["id"]: 0 for c in candidates}
        for (cid, _fid), receipt in parsed.items():
            net, cost = _net(receipt, factors)
            totals[cid] += net
            costs[cid] += cost
            negative_folds[cid] += int(net <= 0)
        winner = sorted(totals, key=lambda cid: (-totals[cid], cid))[0]
        scenario_results[name] = {
            "declaredNetPnlByCandidate": {cid: str(totals[cid]) for cid in sorted(totals)},
            "declaredTotalCostsByCandidate": {cid: str(costs[cid]) for cid in sorted(costs)},
            "nonpositiveFoldCountByCandidate": {cid: negative_folds[cid] for cid in sorted(totals)},
            "diagnosticBestNetCandidateId": winner,
            "selectedCandidateDeclaredNetPnl": str(totals[census["selectedCandidateId"]]),
        }
    selected = census["selectedCandidateId"]
    for cid in scenario_results["baseline"]["declaredNetPnlByCandidate"]:
        baseline_net = Decimal(scenario_results["baseline"]["declaredNetPnlByCandidate"][cid])
        if any(Decimal(s["declaredNetPnlByCandidate"][cid]) > baseline_net
               for s in scenario_results.values()):
            raise ValueError("Adverse execution stress improved declared net result")
    return {
        "engine": "development-cost-stress-v1", "status": "DECLARED_COSTS_ONLY",
        "registrationManifestSha256": census["registrationManifestSha256"],
        "postOutcomeCostReceiptSha256": _digest({
            "registrationManifestSha256": census["registrationManifestSha256"],
            "selection": selection, "receipts": sorted(receipts, key=lambda r: (r["candidateId"], r["foldId"])),
            "stresses": sorted(stresses, key=lambda r: r["id"]),
        }),
        "provider": source[0], "venue": source[1], "instrument": source[2],
        "accountAlias": account, "settlementCurrency": currency,
        "candidateCount": len(candidates), "foldCount": len(folds),
        "receiptCount": len(receipts), "selectedCandidateId": selected,
        "scenarios": scenario_results,
        "selectedCandidateNetWinnerUnderEveryStress": all(
            s["diagnosticBestNetCandidateId"] == selected for s in scenario_results.values()),
        "sourceAuthenticated": False, "costReceiptsAuthenticated": False,
        "brokerFinancingVerified": False, "validationHoldoutAccess": False,
        "profitabilityEstablished": False,
        "mayExecutePaperOrder": False, "mayExecuteLiveOrder": False,
        "warning": ("All gross P&L, costs, statements, clocks and account aliases are caller-declared. "
                    "A post-outcome hash is not independent custody; zero charges are not proven free. "
                    "No untouched holdout, executable liquidity, verified CFD financing, statistical "
                    "significance, real net-of-cost return or profitable edge is established."),
    }
