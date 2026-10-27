"""Verify a detached Ed25519 signature over declared M1 off-journal anchors.

This proves only that the envelope was signed by the supplied public key.
Independent key custody, witness clock, provider prices and rights remain
unverified. No signing keys, network, broker access or order permissions.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .declared_m1_receipt_anchor_audit import (
    _FIELDS, _WITNESS, _key, audit_declared_m1_receipt_anchor_evidence,
)
from .expected_bar_manifest import ExpectedM1Manifest

PROTOCOL = "declared-m1-receipt-signed-witness-v1"
DOMAIN = b"trading-strategy-lab:declared-m1-receipt-witness:v1\n"
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEX128 = re.compile(r"[0-9a-f]{128}\Z")
_MAX_MESSAGE_BYTES = 16_384


def _canonical_signed_message(payload):
    """Domain-separated, deterministic UTF-8 bytes; never sign raw JSON text."""
    return DOMAIN + json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=True, allow_nan=False,
    ).encode("ascii")


def audit_signed_declared_m1_receipt_anchor_evidence(
    db_path, manifest, envelope, evaluation_as_of_utc,
    trusted_public_key_hex, trusted_public_key_sha256, *,
    trusted_witness_id=None, trusted_floor=None,
):
    """Check signature against an *externally pinned* key, then journal chain.

    The trusted key and fingerprint must be provisioned by the operator through
    an independently controlled channel, never learned from this envelope.
    The signature is not proof of witness independence or trustworthy time.
    """
    if trusted_witness_id is not None and (
        type(trusted_witness_id) is not str
        or not _WITNESS.fullmatch(trusted_witness_id)
    ):
        raise ValueError("Invalid independently pinned witness identifier")
    if type(manifest) is not ExpectedM1Manifest:
        raise ValueError("Compiled M1 manifest required")
    # This floor must be obtained from a separate operator-controlled record.
    # It protects against jointly replaying an older *valid* journal and
    # older *valid* signed envelope. It does not establish external custody.
    if trusted_floor is not None:
        if (type(trusted_floor) is not dict
                or set(trusted_floor) != {
                    "scope_key", "revision", "checkpoint_sha256", "witness_id",
                }
                or trusted_floor["scope_key"] != _key(manifest)
                or type(trusted_floor["revision"]) is not int
                or trusted_floor["revision"] <= 0
                or type(trusted_floor["checkpoint_sha256"]) is not str
                or not _HEX64.fullmatch(trusted_floor["checkpoint_sha256"])
                or trusted_witness_id is None
                or trusted_floor["witness_id"] != trusted_witness_id):
            raise ValueError("Invalid independently pinned checkpoint floor")
    if type(evaluation_as_of_utc) is not int or evaluation_as_of_utc <= 0:
        raise ValueError("Invalid evaluation cutoff")
    if type(envelope) is not dict or set(envelope) != {"payload", "signature_hex"}:
        raise ValueError("Invalid signed witness envelope")
    payload = envelope["payload"]
    if type(payload) is not dict or set(payload) != {
        "protocol", "scope_key", "issued_at_utc", "anchors",
    }:
        raise ValueError("Invalid signed witness payload")
    if payload["protocol"] != PROTOCOL or payload["scope_key"] != _key(manifest):
        raise ValueError("Signed witness protocol or scope mismatch")
    issued = payload["issued_at_utc"]
    anchors = payload["anchors"]
    if (type(issued) is not int or not 0 < issued <= evaluation_as_of_utc
            or type(anchors) not in (list, tuple) or not 1 <= len(anchors) <= 16):
        raise ValueError("Invalid signed witness chronology or population")
    # Bound untrusted nested values before serialization and verification.
    for anchor in anchors:
        if type(anchor) is not dict or set(anchor) != _FIELDS:
            raise ValueError("Invalid signed anchor shape")
        for value in anchor.values():
            if type(value) is str:
                if len(value) > 160:
                    raise ValueError("Unbounded signed anchor field")
            elif type(value) is not int:
                raise ValueError("Invalid signed anchor field type")
        if (trusted_witness_id is not None
                and anchor["witness_id"] != trusted_witness_id):
            raise ValueError("Signed anchor witness identity differs from operator pin")
        if (type(anchor["witnessed_at_utc"]) is not int
                or anchor["witnessed_at_utc"] > issued):
            raise ValueError("Signed witness issued before claimed observation")
    signature_hex = envelope["signature_hex"]
    if type(signature_hex) is not str or not _HEX128.fullmatch(signature_hex):
        raise ValueError("Invalid witness signature encoding")
    if (type(trusted_public_key_hex) is not str
            or not _HEX64.fullmatch(trusted_public_key_hex)
            or type(trusted_public_key_sha256) is not str
            or not _HEX64.fullmatch(trusted_public_key_sha256)):
        raise ValueError("Invalid pinned witness public key")
    public_key = bytes.fromhex(trusted_public_key_hex)
    if not hmac.compare_digest(
        hashlib.sha256(public_key).hexdigest(), trusted_public_key_sha256,
    ):
        raise ValueError("Pinned witness key fingerprint mismatch")
    message = _canonical_signed_message(payload)
    if len(message) > _MAX_MESSAGE_BYTES:
        raise ValueError("Signed witness evidence exceeds size bound")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(signature_hex), message,
        )
    except (InvalidSignature, ValueError):
        raise ValueError("Detached witness signature verification failed") from None

    if trusted_floor is not None and not any(
        anchor["revision"] == trusted_floor["revision"]
        and anchor["checkpoint_sha256"] == trusted_floor["checkpoint_sha256"]
        for anchor in anchors
    ):
        raise ValueError("Signed anchors omit operator-pinned checkpoint floor")

    # Revalidate the entire SQLite chain and all chronology/scope constraints
    # after cryptographic verification. Never convert a HOLD into approval.
    result = audit_declared_m1_receipt_anchor_evidence(
        db_path, manifest, anchors, evaluation_as_of_utc,
    )
    result.update({
        "protocol": PROTOCOL,
        "signed_envelope_sha256": hashlib.sha256(message).hexdigest(),
        "signed_witness_issued_at_utc": issued,
        "signature_verified_against_supplied_key": True,
        "operator_pinned_key_fingerprint_matched": True,
        "witness_id_matched_operator_pin": trusted_witness_id is not None,
        "operator_pinned_checkpoint_floor_matched": trusted_floor is not None,
        "external_witness_authenticated": False,
        "independent_custody_verified": False,
        "trusted_witness_clock_verified": False,
        "provider_authenticated": False,
        "provider_entitlement_verified": False,
        "live": False,
        "may_execute_order": False,
    })
    return result
