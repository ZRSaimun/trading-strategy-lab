"""Synthetic offline Ed25519 witness signatures for declared M1 journals."""
import hashlib
import json
import sqlite3

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.expected_bar_manifest import compile_expected_m1_manifest
from app.declared_m1_receipt_sqlite_journal import (
    _key, append_declared_m1_checkpoint,
)
from app.declared_m1_receipt_signed_witness import (
    DOMAIN, PROTOCOL, audit_signed_declared_m1_receipt_anchor_evidence,
)

T = 1790000040
ZERO = "0" * 64
BASE = dict(provider="fixture", symbol="XAU/USD", venue="synthetic",
            price_side="BID", calendar_id="fixture", calendar_revision="r1",
            calendar_source="operator declared UTC schedule", exclusions_utc=[])


def _manifest(now, sessions):
    return compile_expected_m1_manifest(
        **(BASE | dict(observed_at_utc=now, sessions_utc=sessions)))


def _bar(t):
    return dict(provider="fixture", symbol="XAU/USD", venue="synthetic",
                price_side="BID", bar_start_utc=t, received_at_utc=t + 65,
                open=100., high=102., low=99., close=101.)


def _anchor(report, scope, observed, witnessed, ref):
    return {
        "scope_key": scope, "revision": report["revision"],
        "checkpoint_sha256": report["checkpoint_sha256"],
        "previous_checkpoint_sha256": report["previous_checkpoint_sha256"],
        "declared_observed_at_utc": observed, "witnessed_at_utc": witnessed,
        "witness_id": "synthetic-witness", "evidence_ref": ref,
    }


def _fixture(tmp_path):
    p = _manifest(T + 180, [(T, T + 120)])
    c = _manifest(T + 300, [(T, T + 120), (T + 180, T + 240)])
    path = tmp_path / "receipt.sqlite"
    first = append_declared_m1_checkpoint(path, [_bar(T), _bar(T + 60)], p, ZERO)
    second = append_declared_m1_checkpoint(
        path, [_bar(T), _bar(T + 60), _bar(T + 180)],
        c, first["checkpoint_sha256"],
    )
    scope = _key(p)
    anchors = [
        _anchor(first, scope, T + 180, T + 200, "offjournal:one"),
        _anchor(second, scope, T + 300, T + 320, "offjournal:two"),
    ]
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return path, p, first, anchors, key, public.hex(), hashlib.sha256(public).hexdigest()


def _signed(key, anchors, scope, issued=T + 330):
    payload = {
        "protocol": PROTOCOL, "scope_key": scope,
        "issued_at_utc": issued, "anchors": anchors,
    }
    message = DOMAIN + json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")
    return {"payload": payload, "signature_hex": key.sign(message).hex()}


def _check(path, manifest, envelope, pub, pin, cutoff=T + 400):
    return audit_signed_declared_m1_receipt_anchor_evidence(
        path, manifest, envelope, cutoff, pub, pin,
    )


def test_matching_signature_and_local_chain_do_not_claim_external_trust(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    result = _check(path, manifest, envelope, pub, pin)
    assert result["status"] == "DECLARED_HEAD_ANCHOR_MATCH_ONLY"
    assert result["signature_verified_against_supplied_key"] is True
    assert result["operator_pinned_key_fingerprint_matched"] is True
    assert result["external_witness_authenticated"] is False
    assert result["independent_custody_verified"] is False
    assert result["trusted_witness_clock_verified"] is False
    assert result["live"] is False and result["may_execute_order"] is False
    assert result["signed_envelope_sha256"] != anchors[-1]["checkpoint_sha256"]


def test_independent_witness_identity_pin_matches_signed_anchors(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    matched = audit_signed_declared_m1_receipt_anchor_evidence(
        path, manifest, envelope, T + 400, pub, pin,
        trusted_witness_id="synthetic-witness",
    )
    assert matched["witness_id_matched_operator_pin"] is True
    unpinned = _check(path, manifest, envelope, pub, pin)
    assert unpinned["witness_id_matched_operator_pin"] is False


@pytest.mark.parametrize("pin", [
    "other-witness", "", "a" * 81, True, 123, "invalid witness",
])
def test_wrong_or_invalid_operator_witness_pin_fails_closed(tmp_path, pin):
    path, manifest, _, anchors, key, pub, fingerprint = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    with pytest.raises(ValueError, match="witness"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, envelope, T + 400, pub, fingerprint,
            trusted_witness_id=pin,
        )


def test_valid_signature_with_mixed_claimed_witnesses_rejected_by_pin(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    anchors[1]["witness_id"] = "different-witness"
    # A valid signature alone must not authorize claiming another witness ID.
    envelope = _signed(key, anchors, _key(manifest))
    with pytest.raises(ValueError, match="witness identity"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, envelope, T + 400, pub, pin,
            trusted_witness_id="synthetic-witness",
        )


def test_signed_older_head_stays_on_hold(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    result = _check(path, manifest, _signed(key, anchors[:1], _key(manifest)), pub, pin)
    assert result["status"] == "HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED"


@pytest.mark.parametrize("mutation", [
    lambda e: e["payload"]["anchors"][-1].update(checkpoint_sha256="f" * 64),
    lambda e: e["payload"]["anchors"][-1].update(witnessed_at_utc=T + 321),
    lambda e: e["payload"].update(issued_at_utc=T + 331),
    lambda e: e["payload"].update(scope_key="f" * 64),
    lambda e: e.update(signature_hex="f" * 128),
    lambda e: e["payload"].update(extra="unexpected"),
])
def test_tampering_or_unexpected_fields_fail_closed(tmp_path, mutation):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    mutation(envelope)
    with pytest.raises(ValueError):
        _check(path, manifest, envelope, pub, pin)


def test_wrong_public_key_or_pin_is_rejected(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    other = Ed25519PrivateKey.generate().public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    with pytest.raises(ValueError, match="fingerprint"):
        _check(path, manifest, envelope, pub, "0" * 64)
    with pytest.raises(ValueError, match="signature"):
        _check(path, manifest, envelope, other.hex(), hashlib.sha256(other).hexdigest())


@pytest.mark.parametrize("issued,cutoff", [
    (T + 319, T + 400), (T + 401, T + 400), (True, T + 400),
])
def test_invalid_signed_issue_time_or_cutoff_fails_closed(tmp_path, issued, cutoff):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    with pytest.raises(ValueError):
        _check(path, manifest, _signed(key, anchors, _key(manifest), issued), pub, pin, cutoff)


def test_signed_claim_cannot_hide_consistent_database_rollback(tmp_path):
    path, manifest, first, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM declared_m1_snapshots WHERE revision=2")
        conn.execute(
            "UPDATE declared_m1_heads SET revision=1, head_sha256=?",
            (first["checkpoint_sha256"],),
        )
    with pytest.raises(ValueError, match="rolled-back"):
        _check(path, manifest, envelope, pub, pin)


def test_no_external_signature_or_key_generation_side_effects(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    with pytest.raises(ValueError, match="signature"):
        _check(path, manifest, envelope | {"signature_hex": "0" * 128}, pub, pin)
    with pytest.raises(ValueError, match="envelope"):
        _check(path, manifest, envelope | {"private_key": "not accepted"}, pub, pin)


def _trusted_floor(anchor):
    return {
        "scope_key": anchor["scope_key"],
        "revision": anchor["revision"],
        "checkpoint_sha256": anchor["checkpoint_sha256"],
        "witness_id": anchor["witness_id"],
    }


def test_operator_floor_matches_signed_anchor_and_does_not_grant_trust(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    result = audit_signed_declared_m1_receipt_anchor_evidence(
        path, manifest, _signed(key, anchors, _key(manifest)),
        T + 400, pub, pin,
        trusted_witness_id="synthetic-witness",
        trusted_floor=_trusted_floor(anchors[-1]),
    )
    assert result["operator_pinned_checkpoint_floor_matched"] is True
    assert result["status"] == "DECLARED_HEAD_ANCHOR_MATCH_ONLY"
    assert result["independent_custody_verified"] is False
    assert result["live"] is False and result["may_execute_order"] is False


def test_valid_older_signature_cannot_satisfy_newer_operator_floor(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    with pytest.raises(ValueError, match="operator-pinned checkpoint floor"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, _signed(key, anchors[:1], _key(manifest)),
            T + 400, pub, pin, trusted_witness_id="synthetic-witness",
            trusted_floor=_trusted_floor(anchors[-1]),
        )


def test_jointly_replayed_valid_journal_and_signature_fail_operator_floor(tmp_path):
    path, manifest, first, anchors, key, pub, pin = _fixture(tmp_path)
    older_envelope = _signed(key, anchors[:1], _key(manifest))
    with sqlite3.connect(path) as conn:
        conn.execute("DELETE FROM declared_m1_snapshots WHERE revision=2")
        conn.execute(
            "UPDATE declared_m1_heads SET revision=1, head_sha256=?",
            (first["checkpoint_sha256"],),
        )
    # Both the older journal and older signature are internally consistent.
    assert _check(path, manifest, older_envelope, pub, pin)["status"] == (
        "DECLARED_HEAD_ANCHOR_MATCH_ONLY"
    )
    with pytest.raises(ValueError, match="operator-pinned checkpoint floor"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, older_envelope, T + 400, pub, pin,
            trusted_witness_id="synthetic-witness",
            trusted_floor=_trusted_floor(anchors[-1]),
        )


@pytest.mark.parametrize("change", [
    lambda floor: floor.update(revision=0),
    lambda floor: floor.update(revision=True),
    lambda floor: floor.update(checkpoint_sha256="X" * 64),
    lambda floor: floor.update(scope_key="0" * 64),
    lambda floor: floor.update(witness_id="another-witness"),
    lambda floor: floor.update(extra="unexpected"),
])
def test_invalid_independent_floor_fails_closed(tmp_path, change):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    floor = _trusted_floor(anchors[-1])
    change(floor)
    with pytest.raises(ValueError, match="checkpoint floor"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, _signed(key, anchors, _key(manifest)),
            T + 400, pub, pin, trusted_witness_id="synthetic-witness",
            trusted_floor=floor,
        )


def test_operator_floor_requires_separate_witness_identity_pin(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    with pytest.raises(ValueError, match="checkpoint floor"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, _signed(key, anchors, _key(manifest)),
            T + 400, pub, pin, trusted_floor=_trusted_floor(anchors[-1]),
        )


def test_valid_old_floor_does_not_override_unanchored_newer_head(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    result = audit_signed_declared_m1_receipt_anchor_evidence(
        path, manifest, _signed(key, anchors[:1], _key(manifest)),
        T + 400, pub, pin, trusted_witness_id="synthetic-witness",
        trusted_floor=_trusted_floor(anchors[0]),
    )
    assert result["operator_pinned_checkpoint_floor_matched"] is True
    assert result["status"] == "HOLD_LOCAL_HEAD_NOT_EXTERNALLY_ANCHORED"



def test_optional_declared_age_gate_accepts_exact_latest_anchor_boundary(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    report = audit_signed_declared_m1_receipt_anchor_evidence(
        path, manifest, _signed(key, anchors, _key(manifest)),
        T + 400, pub, pin, max_declared_witness_age_seconds=80,
    )
    assert report["declared_witness_age_policy_checked"] is True
    assert report["declared_witness_issued_age_seconds"] == 70
    assert report["declared_last_anchor_age_seconds"] == 80
    assert report["trusted_witness_clock_verified"] is False
    assert report["live"] is False and report["may_execute_order"] is False


def test_declared_age_gate_rejects_old_anchor_even_if_recently_signed(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    # Issued one second before evaluation; last witnessed anchor is 80s old.
    envelope = _signed(key, anchors, _key(manifest), issued=T + 399)
    with pytest.raises(ValueError, match="stale"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, envelope, T + 400, pub, pin,
            max_declared_witness_age_seconds=60,
        )


def test_declared_age_gate_rejects_old_signed_envelope(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    envelope = _signed(key, anchors, _key(manifest))
    with pytest.raises(ValueError, match="stale"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, envelope, T + 400, pub, pin,
            max_declared_witness_age_seconds=60,
        )


@pytest.mark.parametrize("policy", [
    True, False, 0, -1, 86401, 60.0, "60", [], {},
])
def test_invalid_declared_age_policy_fails_closed(tmp_path, policy):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    with pytest.raises(ValueError, match="age policy"):
        audit_signed_declared_m1_receipt_anchor_evidence(
            path, manifest, _signed(key, anchors, _key(manifest)),
            T + 400, pub, pin, max_declared_witness_age_seconds=policy,
        )


def test_age_policy_opt_in_preserves_existing_callers(tmp_path):
    path, manifest, _, anchors, key, pub, pin = _fixture(tmp_path)
    report = _check(path, manifest, _signed(key, anchors, _key(manifest)), pub, pin)
    assert report["declared_witness_age_policy_checked"] is False
    assert report["declared_witness_issued_age_seconds"] is None
    assert report["declared_last_anchor_age_seconds"] is None
