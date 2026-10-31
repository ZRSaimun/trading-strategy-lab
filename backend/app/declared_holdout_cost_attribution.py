"""Offline exact-decimal attribution of *declared* holdout costs.

This is a post-validation accounting view, not broker execution evidence.
The underlying holdout gate controls membership, receipts, and withholding.
No networking, order submission, source ingestion, or market-data access.
"""
from __future__ import annotations

from decimal import Decimal, localcontext

from .declared_holdout_release_gate import audit_declared_holdout_release, _money

_FIELDS = ("gross_cash", "spread_cash", "slippage_cash", "commission_cash",
           "financing_cash", "fx_cash")
_OUTPUTS = _FIELDS + ("financing_debit_cash", "financing_credit_cash",
                     "nonfinancing_charges_cash", "net_cost_cash", "net_cash")


def audit_declared_holdout_cost_attribution(
    manifest, census, anchor, outcomes, release_at_utc
):
    """Reconcile costs only after the full declared holdout release audit.

    For fewer than 30 observations, return no outcome-derived amounts.
    Signed financing is a debit when positive and a credit when negative.
    These numbers are NOT executable broker costs or a profitability claim.
    """
    release = audit_declared_holdout_release(
        manifest, census, anchor, outcomes, release_at_utc
    )
    result = {
        "protocol": "declared-holdout-cost-attribution-v1",
        "status": release["status"],
        "manifest_sha256": release["manifest_sha256"],
        "outcome_receipts_sha256": release["outcome_receipts_sha256"],
        "observation_count": release["observation_count"],
        "outcome_metrics_withheld": release["outcome_metrics_withheld"],
        **{field: None for field in _OUTPUTS},
        "source_bytes_independently_authenticated": False,
        "holdout_untouched_independently_verified": False,
        "broker_costs_verified": False,
        "profitable_edge_verified": False,
        "may_execute_demo_order": False,
        "may_execute_real_order": False,
        "warning": "Caller-declared cash amounts and receipts only; no verified "
                   "broker BID/ASK, financing, fills, FX conversion or equity risk. "
                   "Withheld populations reveal no outcome-derived totals.",
    }
    if release["outcome_metrics_withheld"]:
        return result

    with localcontext() as ctx:
        ctx.prec = 80
        totals = {
            field: sum(
                (_money(row[field], nonnegative=field not in
                        ("gross_cash", "financing_cash")) for row in outcomes),
                Decimal(0),
            )
            for field in _FIELDS
        }
        debits = sum(
            (_money(row["financing_cash"]) for row in outcomes
             if _money(row["financing_cash"]) > 0), Decimal(0)
        )
        credits = -sum(
            (_money(row["financing_cash"]) for row in outcomes
             if _money(row["financing_cash"]) < 0), Decimal(0)
        )
        charges = sum(
            (totals[field] for field in
             ("spread_cash", "slippage_cash", "commission_cash", "fx_cash")),
            Decimal(0),
        )
        net_cost = charges + totals["financing_cash"]
        net = totals["gross_cash"] - net_cost
        if format(net, ".4f") != release["net_cash"]:
            raise RuntimeError("Declared cost attribution does not reconcile")
        amounts = {
            **totals,
            "financing_debit_cash": debits,
            "financing_credit_cash": credits,
            "nonfinancing_charges_cash": charges,
            "net_cost_cash": net_cost,
            "net_cash": net,
        }
        result.update({key: format(value, ".4f") for key, value in amounts.items()})
    return result
