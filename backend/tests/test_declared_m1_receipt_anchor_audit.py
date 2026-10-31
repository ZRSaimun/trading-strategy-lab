"""Synthetic, offline regression tests for M1 off-journal anchor claims."""
import sqlite3

import pytest

from app.expected_bar_manifest import compile_expected_m1_manifest
from app.declared_m1_receipt_sqlite_journal import append_declared_m1_checkpoint
from app.declared_m1_receipt_anchor_audit import audit_declared_m1_receipt_anchor_evidence

T = 1790000040
ZERO = "0" * 64
BASE = dict(provider="fixture", symbol="XAU/USD", venue="synthetic",
            price_side="BID", calendar_id="fixture", calendar_revision="r1",
            calendar_source="operator declared UTC schedule", exclusions_utc=[])


def manifest(now, sessions):
    return compile_expected_m1_manifest(
        **(BASE | dict(observed_at_utc=now, sessions_utc=sessions)))


def bar(t):
    return dict(provider="fixture", symbol="XAU/USD", venue="synthetic",
                price_side="BID", bar_start_utc=t, received_at_utc=t + 65,
                open=100., high=102., low=99., close=101.)


P = manifest(T + 180, [(T, T + 120)])
C = manifest(T + 300, [(T, T + 120), (T + 180, T + 240)])
OLD = [bar(T), bar(T + 60)]
NEW = OLD + [bar(T + 180)]


def anchor(report, observed, witnessed, ref):
    return dict(scope_key=report["scope_key"] if "scope_key" in report else None,
                revision=report["revision"],
                checkpoint_sha256=report["checkpoint_sha256"],
                previous_checkpoint_sha256=report["previous_checkpoint_sha256"],
                declared_observed_at_utc=observed,
                witnessed_at_utc=witnessed, witness_id="fixture-witness",
                evidence_ref=ref)


def setup(tmp_path):
    path = tmp_path / "receipts.db"
    first = append_declared_m1_checkpoint(path, OLD, P, ZERO)
    second = append_declared_m1_checkpoint(path, NEW, C, first["checkpoint_sha256"])
    # The journal report intentionally does not expose a scope key.
    from app.declared_m1_receipt_sqlite_journal import _key
    a = anchor(first, P.observed_at_utc, T + 200, "offline:one")
    b = anchor(second, C.observed_at_utc, T + 320, "offline:two")
    a["scope_key"] = b["scope_key"] = _key(P)
    return path, first, second, a, b


def audit(path, anchors, cutoff=T + 400):
    return audit_declared_m1_receipt_anchor_evidence(path, P, anchors, cutoff)


def test_matching_anchor_population_and_read_only(tmp_path):
    path, first, second, a, b = setup(tmp_path)
    result = audit(path, [a, b])
    assert result["status"] == "DECLARED_HEAD_ANCHOR_MATCH_ONLY"
    assert result["local_head_sha256"] == second["checkpoint_sha256"]
    assert result["head_has_matching_declared_anchor"] is True
    assert result["external_witness_authenticated"] is False
    assert result["live"] is False and result["may_execute_order"] is False


def test_unanchored_newer_head_remains_on_hold(tmp_path):
    path, _, _, a, _ = setup(tmp_path)
    result = audit(path, [a])
    assert result["status"] == "HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED"
    assert result["head_has_matching_declared_anchor"] is False


def test_consistent_database_rollback_is_caught_by_anchor(tmp_path):
    path, first, _, a, b = setup(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM declared_m1_snapshots WHERE revision=2")
        conn.execute("UPDATE declared_m1_heads SET revision=1, head_sha256=?",
                     (first["checkpoint_sha256"],))
    with pytest.raises(ValueError, match="rolled-back"):
        audit(path, [a, b])


@pytest.mark.parametrize("change", [
    lambda a, b: b.update(checkpoint_sha256="f" * 64),
    lambda a, b: b.update(previous_checkpoint_sha256="f" * 64),
    lambda a, b: b.update(scope_key="f" * 64),
    lambda a, b: b.update(declared_observed_at_utc=T + 301),
    lambda a, b: b.update(witnessed_at_utc=T + 299),
    lambda a, b: b.update(witnessed_at_utc=T + 500),
    lambda a, b: b.update(evidence_ref=a["evidence_ref"]),
    lambda a, b: b.update(revision=True),
    lambda a, b: b.update(witness_id="unsafe witness"),
    lambda a, b: b.update(extra="unexpected"),
])
def test_invalid_or_conflicting_anchor_rejected(tmp_path, change):
    path, _, _, a, b = setup(tmp_path)
    change(a, b)
    with pytest.raises(ValueError):
        audit(path, [a, b])


def test_nonascending_and_wrong_evaluation_cutoff_rejected(tmp_path):
    path, _, _, a, b = setup(tmp_path)
    with pytest.raises(ValueError, match="nonascending"):
        audit(path, [b, a])
    with pytest.raises(ValueError, match="cutoff"):
        audit(path, [a, b], T + 250)
    with pytest.raises(ValueError, match="cutoff"):
        audit(path, [a, b], True)


def test_tampered_journal_is_rejected_even_with_matching_claims(tmp_path):
    path, _, _, a, b = setup(tmp_path)
    with sqlite3.connect(path) as conn:
        conn.execute("UPDATE declared_m1_snapshots SET checkpoint_sha256=? WHERE revision=2",
                     ("e" * 64,))
    with pytest.raises(ValueError):
        audit(path, [a, b])


def test_empty_anchor_population_rejected(tmp_path):
    path, _, _, _, _ = setup(tmp_path)
    with pytest.raises(ValueError, match="nonempty"):
        audit(path, [])
