"""Synthetic and end-to-end regressions for declared NET_CLOSE cash postings."""
import copy
from decimal import Decimal

import pytest

from app import declared_cash_posting_audit as mod
from app.financing_position_population import fingerprint_financing_position_population
from app.declared_roundtrip_cost_audit import fingerprint_roundtrip_specs
from app.declared_fx_conversion_audit import fingerprint_fx_conversion_policy
from app.declared_fx_rounding_sensitivity import fingerprint_fx_rounding_policy
from test_declared_fx_conversion_audit import inputs


def setup():
    manifest, specs, versions, fills, fx_policy, quotes = inputs()
    finance_sha = fingerprint_financing_position_population(manifest)
    specs_sha = fingerprint_roundtrip_specs(manifest, specs, finance_sha)
    fx_sha = fingerprint_fx_conversion_policy(manifest, fx_policy, finance_sha, specs_sha)
    rounding = {"reporting_minor_units": 2, "rounding_mode": "HALF_EVEN"}
    rounding_sha = fingerprint_fx_rounding_policy(fx_sha, 500, rounding)
    posting_policy = {"max_posting_delay_seconds": 10, "max_receipt_lag_seconds": 10}
    posting_sha = mod.fingerprint_cash_posting_policy(
        manifest, fx_policy, fx_sha, rounding_sha, 500, posting_policy,
    )
    def receipt(pid, closed, cash):
        return {
            "receipt_id": "cash-" + pid, "position_id": pid,
            "provider": "Synthetic", "venue": "DEMO", "account_alias": "paper1",
            "currency": "USD", "kind": "NET_CLOSE", "posted_at": closed + 1,
            "received_at": closed + 2, "amount_cash": cash,
            "statement_sha256": "d" * 64,
        }
    return dict(
        manifest=manifest, financing_versions=versions,
        expected_financing_sha256=finance_sha, specs=specs,
        expected_specs_sha256=specs_sha, fills=fills, cutoff=500,
        fx_policy=fx_policy, expected_fx_policy_sha256=fx_sha, fx_quotes=quotes,
        rounding_policy=rounding, expected_rounding_policy_sha256=rounding_sha,
        posting_policy=posting_policy, expected_posting_policy_sha256=posting_sha,
        postings=[receipt("p1", 400, "16.92"), receipt("p2", 450, "8.98")],
    )


def run(data=None):
    return mod.audit_declared_cash_postings(**(setup() if data is None else data))


def test_end_to_end_financing_fills_fx_rounding_to_cash():
    result = run()
    assert result["status"] == "COMPLETE_SELF_DECLARED_ONLY"
    assert result["reconciled_reporting_cash"] == "25.90"
    assert result["expected_positions"] == 2
    assert result["mismatches"] == []
    for flag in ("source_authenticated", "broker_settlement_verified",
                 "untouched_holdout_verified", "verified_profitability", "may_execute_order"):
        assert result[flag] is False


def test_missing_posting_withholds_not_zero():
    data = setup()
    data["postings"].pop()
    result = run(data)
    assert result["status"] == "WITHHELD_INCOMPLETE_DECLARED_POSTINGS"
    assert result["missing_position_ids"] == ["p2"]
    assert result["reconciled_reporting_cash"] is None


def test_mismatch_is_measured_but_not_aggregated():
    data = setup()
    data["postings"][0]["amount_cash"] = "16.91"
    result = run(data)
    assert result["status"] == "MISMATCH_DECLARED_POSTINGS"
    assert result["reconciled_reporting_cash"] is None
    assert result["mismatches"] == [{
        "position_id": "p1", "hypothetical_rounded_cash": "16.92",
        "declared_posted_cash": "16.91", "difference_cash": "-0.01",
    }]


def test_reordered_receipts_deterministic_and_unchanged():
    data = setup()
    original = copy.deepcopy(data)
    first = run(data)
    data["postings"].reverse()
    assert run(data) == first
    assert original["postings"] == list(reversed(data["postings"]))


def test_later_financing_revision_breaks_earlier_posting_match():
    data = setup()
    data["financing_versions"].append(dict(
        data["financing_versions"][0], receipt_id="later-revision",
        revision=2, amount_currency="2.00", published_at=490, ingested_at=495,
    ))
    result = run(data)
    assert result["status"] == "MISMATCH_DECLARED_POSTINGS"
    assert result["reconciled_reporting_cash"] is None


def test_incomplete_financing_withholds_cash_reconciliation():
    data = setup()
    data["financing_versions"].pop()
    result = run(data)
    assert result["status"] == "WITHHELD_INCOMPLETE_UPSTREAM"
    assert result["reconciled_reporting_cash"] is None


@pytest.mark.parametrize("field,value", [
    ("provider", "Other"), ("venue", "LIVE"), ("account_alias", "other"),
    ("currency", "GBP"), ("kind", "FEE"), ("receipt_id", ""),
    ("statement_sha256", "bad"), ("posted_at", 399), ("posted_at", 412),
    ("received_at", 400), ("received_at", 420), ("received_at", 501),
    ("posted_at", True), ("received_at", 450.0), ("amount_cash", "NaN"),
    ("amount_cash", "1e2"), ("amount_cash", "16.920"),
    ("amount_cash", "-0.00"), ("amount_cash", "1" * 81),
    ("extra", "bad"),
])
def test_invalid_receipt_rejected(field, value):
    data = setup()
    data["postings"][0][field] = value
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("mutate", [
    lambda p: p.append(copy.deepcopy(p[0])),
    lambda p: p.__setitem__(1, dict(p[1], receipt_id="cash-p1")),
    lambda p: p.__setitem__(1, dict(p[1], position_id="unknown")),
    lambda p: p.__setitem__(1, dict(p[1], position_id="p1")),
])
def test_duplicates_extra_and_reused_receipt_ids_rejected(mutate):
    data = setup()
    mutate(data["postings"])
    with pytest.raises(ValueError):
        run(data)


@pytest.mark.parametrize("key,value", [
    ("max_posting_delay_seconds", True),
    ("max_posting_delay_seconds", -1),
    ("max_posting_delay_seconds", 2592001),
    ("max_receipt_lag_seconds", 2.5),
    ("extra", 5),
])
def test_invalid_policy_rejected(key, value):
    data = setup()
    data["posting_policy"][key] = value
    with pytest.raises(ValueError):
        run(data)


def test_changed_policy_requires_new_digest():
    data = setup()
    data["posting_policy"]["max_posting_delay_seconds"] = 11
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_changed_close_anchor_requires_new_digest():
    data = setup()
    data["manifest"]["positions"][0]["closed_at"] = 401
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_wrong_fx_policy_or_rounding_fingerprint_rejected():
    data = setup()
    data["expected_fx_policy_sha256"] = "b" * 64
    with pytest.raises(ValueError, match="digest mismatch"):
        run(data)


def test_bounded_empty_receipt_population_withholds():
    data = setup()
    data["postings"] = []
    result = run(data)
    assert result["observed_positions"] == 0
    assert result["reconciled_reporting_cash"] is None


def test_bounded_population_and_decimal_cash_math():
    data = setup()
    data["postings"] *= 129
    with pytest.raises(ValueError, match="Unbounded"):
        run(data)


def test_declared_receipt_hash_is_not_source_authentication():
    data = setup()
    data["postings"][0]["statement_sha256"] = "e" * 64
    first = run()
    changed = run(data)
    assert changed["receipt_declaration_sha256"] != first["receipt_declaration_sha256"]
    assert changed["broker_settlement_verified"] is False
    assert Decimal(changed["reconciled_reporting_cash"]) == Decimal("25.90")
