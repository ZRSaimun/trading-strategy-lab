"""Synthetic-only, source-aware CFD rate-as-of and cost regressions."""
import copy
import random
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.cfd_rate_decision_audit import (
    audit_declared_cfd_rate_decisions, fingerprint_cfd_rate_decisions,
)


def scope():
    return {
        "protocol": "declared-cfd-rate-decision-audit-v1",
        "source": dict(provider="Synthetic", venue="DEMO", account_alias="paper1",
                       instrument="XAUUSD-CFD", settlement_currency="GBP"),
        "opened_at": 100, "closed_at": 500, "audit_asof": 1000,
        "rollovers": [
            dict(rollover_id="a", rollover_at=200, decision_at=190, side="LONG",
                 notional_cash="10000", day_multiplier=1),
            dict(rollover_id="b", rollover_at=300, decision_at=290, side="SHORT",
                 notional_cash="20000", day_multiplier=3),
        ],
    }


def rate(rid, rollover, revision, published, ingested, long="2.5", short="-1.25"):
    return dict(rate_id=rid, rollover_id=rollover, revision=revision,
                published_at=published, ingested_at=ingested,
                long_bps_per_day=long, short_bps_per_day=short,
                statement_sha256="a" * 64,
                provider="Synthetic", venue="DEMO", account_alias="paper1",
                instrument="XAUUSD-CFD", settlement_currency="GBP")


def rows():
    return [rate("ra", "a", 1, 150, 160), rate("rb", "b", 1, 250, 260)]


def run(s=None, rates=None, digest=None):
    s = scope() if s is None else s
    return audit_declared_cfd_rate_decisions(
        s, rows() if rates is None else rates,
        fingerprint_cfd_rate_decisions(s) if digest is None else digest,
    )


def test_long_short_multiplier_and_signed_cash():
    result = run()
    assert result["status"] == "COMPLETE_SELF_DECLARED_ONLY"
    assert Decimal(result["estimated_financing_cash_unrounded"]) == Decimal("-5")
    assert [Decimal(r["estimated_cash_unrounded"]) for r in result["rollovers"]] == [Decimal("2.5"), Decimal("-7.5")]
    assert result["required_rollovers"] == result["matched_rollovers"] == 2


def test_late_revision_never_rewrites_decision():
    r = rows() + [rate("ra2", "a", 2, 210, 220, long="9")]
    assert run(rates=r)["rollovers"][0]["selected_rate_id"] == "ra"
    assert Decimal(run(rates=r)["estimated_financing_cash_unrounded"]) == Decimal("-5")


def test_revision_known_before_decision_selected():
    r = [rate("ra", "a", 1, 110, 120), rate("ra2", "a", 2, 170, 180, long="3"), rows()[1]]
    assert Decimal(run(rates=r)["estimated_financing_cash_unrounded"]) == Decimal("-4.5")
    assert run(rates=r)["rollovers"][0]["revision"] == 2


def test_missing_rate_withholds_entire_estimate():
    report = run(rates=rows()[:1])
    assert report["status"] == "WITHHELD_MISSING_ASOF_RATE"
    assert report["missing_rollover_ids"] == ["b"]
    assert report["estimated_financing_cash_unrounded"] is None
    assert report["rollovers"][1]["estimated_cash_unrounded"] is None


def test_rate_published_but_not_ingested_before_decision_is_unknown():
    r = [rows()[0], rate("rb", "b", 1, 250, 291)]
    assert run(rates=r)["missing_rollover_ids"] == ["b"]


def test_explicit_zero_rate_is_not_missing():
    r = [rate("ra", "a", 1, 150, 160, long="0"), rate("rb", "b", 1, 250, 260, short="0")]
    assert run(rates=r)["estimated_financing_cash_unrounded"] == "0"


def test_order_independence_input_immutability_and_digest():
    s, r = scope(), rows()
    before = copy.deepcopy((s, r))
    a = run(s, r)
    b = run(s, list(reversed(r)))
    assert a == b and (s, r) == before
    assert len(a["scope_sha256"]) == len(a["rate_declarations_sha256"]) == 64


def test_changed_rate_changes_declaration_not_scope_digest():
    a = run()
    b = run(rates=[dict(rows()[0], long_bps_per_day="3"), rows()[1]])
    assert a["scope_sha256"] == b["scope_sha256"]
    assert a["rate_declarations_sha256"] != b["rate_declarations_sha256"]


def test_stale_scope_digest_rejected():
    s = scope()
    old = fingerprint_cfd_rate_decisions(s)
    s["rollovers"][0]["notional_cash"] = "9999"
    with pytest.raises(ValueError, match="digest mismatch"):
        run(s=s, digest=old)


@pytest.mark.parametrize("change", [
    {"provider": "Other"}, {"venue": "LIVE"}, {"account_alias": "elsewhere"},
    {"instrument": "XAGUSD-CFD"}, {"settlement_currency": "USD"},
    {"rate_id": "ra"}, {"rollover_id": "unknown"}, {"revision": 2},
    {"revision": True}, {"published_at": 261}, {"ingested_at": 1001},
    {"ingested_at": 249}, {"statement_sha256": "BAD"},
    {"long_bps_per_day": "NaN"}, {"short_bps_per_day": "1e3"},
    {"long_bps_per_day": "-0"}, {"short_bps_per_day": "-0.0"},
    {"long_bps_per_day": "100000"}, {"short_bps_per_day": "0.0000001"},
    {"extra": "bad"},
])
def test_malformed_cross_source_or_duplicate_rate_rejected(change):
    with pytest.raises(ValueError):
        run(rates=[rows()[0], dict(rows()[1], **change)])


@pytest.mark.parametrize("mutate", [
    lambda s: s.update(protocol="v2"),
    lambda s: s.update(extra=1),
    lambda s: s["source"].update(provider="bad/name"),
    lambda s: s["source"].update(settlement_currency="gbp"),
    lambda s: s.update(opened_at=True),
    lambda s: s.update(closed_at=200),
    lambda s: s.update(audit_asof=499),
    lambda s: s.update(rollovers=[]),
    lambda s: s["rollovers"].reverse(),
    lambda s: s["rollovers"][1].update(rollover_id="a"),
    lambda s: s["rollovers"][1].update(decision_at=301),
    lambda s: s["rollovers"][0].update(decision_at=99),
    lambda s: s["rollovers"][0].update(rollover_at=500),
    lambda s: s["rollovers"][0].update(notional_cash="-1"),
    lambda s: s["rollovers"][0].update(notional_cash="1e3"),
    lambda s: s["rollovers"][0].update(side="BUY"),
    lambda s: s["rollovers"][0].update(day_multiplier=0),
    lambda s: s["rollovers"][0].update(day_multiplier=8),
    lambda s: s["rollovers"][0].update(day_multiplier=True),
    lambda s: s["rollovers"][0].update(extra=1),
])
def test_invalid_scope_fails_closed(mutate):
    s = scope()
    mutate(s)
    with pytest.raises(ValueError):
        fingerprint_cfd_rate_decisions(s)


def test_duplicate_and_gap_revision_fails_closed():
    for revision in [1, 3]:
        with pytest.raises(ValueError):
            run(rates=rows() + [rate("ra2", "a", revision, 201, 211)])


def test_nonmonotonic_revision_availability_fails_closed():
    with pytest.raises(ValueError, match="Nonmonotonic"):
        run(rates=rows() + [rate("ra2", "a", 2, 140, 180)])
    with pytest.raises(ValueError, match="Nonmonotonic"):
        run(rates=[rate("ra", "a", 1, 150, 185), rows()[1], rate("ra2", "a", 2, 170, 180)])


def test_bounded_populations_and_malformed_expected_digest():
    with pytest.raises(ValueError):
        run(rates=rows() * 5001)
    with pytest.raises(ValueError):
        run(digest="0" * 64)
    with pytest.raises(ValueError):
        run(digest=True)
    s = scope()
    s["rollovers"] = [dict(s["rollovers"][0], rollover_id=f"r{i}", rollover_at=200+i)
                      for i in range(5001)]
    with pytest.raises(ValueError):
        fingerprint_cfd_rate_decisions(s)


def test_eight_year_synthetic_rate_availability_and_missing_year():
    stamps = [int(datetime(y, 1, 10, tzinfo=timezone.utc).timestamp()) for y in range(2019, 2027)]
    s = scope()
    s["opened_at"] = stamps[0] - 1000
    s["closed_at"] = stamps[-1] + 1000
    s["audit_asof"] = stamps[-1] + 2000
    s["rollovers"] = [dict(rollover_id=f"y{y}", rollover_at=t, decision_at=t-10,
                           side="LONG", notional_cash="10000", day_multiplier=1)
                      for y, t in zip(range(2019, 2027), stamps)]
    r = [rate(f"r{y}", f"y{y}", 1, t-30, t-20, long="1")
         for y, t in zip(range(2019, 2027), stamps)]
    assert Decimal(run(s, r)["estimated_financing_cash_unrounded"]) == Decimal("8")
    assert run(s, r[:-1])["estimated_financing_cash_unrounded"] is None


def test_randomized_signed_exact_arithmetic_and_reordering():
    rng = random.Random(113)
    for _ in range(200):
        s = scope()
        a = rng.randrange(-5000, 5001)
        b = rng.randrange(-5000, 5001)
        r = [rate("ra", "a", 1, 150, 160, long=str(a / 100)),
             rate("rb", "b", 1, 250, 260, short=str(b / 100))]
        expected = Decimal(str(a / 100)) + Decimal(str(b / 100)) * 6
        actual = Decimal(run(s, r)["estimated_financing_cash_unrounded"])
        assert actual == expected
        assert run(s, r) == run(s, list(reversed(r)))


def test_safety_flags_are_never_approval_or_profit():
    report = run()
    for field in ("source_authenticated", "complete_broker_calendar_verified",
                  "broker_rounding_verified", "realized_financing_verified",
                  "verified_profitability", "may_execute_order"):
        assert report[field] is False
