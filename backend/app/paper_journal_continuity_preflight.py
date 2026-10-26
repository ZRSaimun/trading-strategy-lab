"""Fail-closed, read-only continuity review for untrusted PAPER journal checkpoints.

This is a diagnostic preflight, NOT a persistence CAS or broker admission gate.
The TypeScript PaperReplayJournal.restore() must independently replay actions
and verify derived orders/events before any journal is considered consistent.
"""
import hashlib
import json
import re

from .paper_journal_store import MAX_CHECKPOINT_BYTES, _checkpoint, _strict_json

_MAX_REVISION = 2**53 - 1
_ORDER_ID = re.compile(r"[A-Za-z0-9_-]{1,80}\\Z")


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def _read(raw):
    if not isinstance(raw, str) or len(raw.encode("utf-8")) > MAX_CHECKPOINT_BYTES:
        raise ValueError("Invalid or oversized paper journal checkpoint")
    try:
        value = _strict_json(raw)
        if not isinstance(value, dict) or not isinstance(value.get("identity"), dict):
            raise ValueError("Missing checkpoint identity")
        _checkpoint(raw, value["identity"])
        return value
    except (ValueError, TypeError, KeyError, RecursionError, OverflowError) as exc:
        raise ValueError("Invalid paper journal checkpoint; manual reconciliation required") from exc


def _order_ids(checkpoint):
    """Return None for malformed, repeated, or unidentifiable paper orders."""
    ids = []
    for order in checkpoint["orders"]:
        if not isinstance(order, dict):
            return None
        value = order.get("clientOrderId")
        if not isinstance(value, str) or not _ORDER_ID.fullmatch(value):
            return None
        ids.append(value)
    if len(ids) != len(set(ids)):
        return None
    return ids


def _prefix(previous, proposed):
    return (len(proposed) >= len(previous)
            and all(_canonical(a) == _canonical(b)
                    for a, b in zip(previous, proposed)))


def review_paper_journal_continuity(previous_json, proposed_json, *,
                                    expected_revision, next_revision):
    """Review append-only history; always HOLD, even when assumptions pass.

    Caller-supplied checkpoints and revisions are unauthenticated. This checks
    that an update cannot erase/rewrite prior actions, events, or order IDs.
    It cannot validate actual fills, market quotes, brokerage acknowledgements,
    or a durable transaction; a trusted server-owned checkpoint is required.
    """
    if (type(expected_revision) is not int or type(next_revision) is not int
            or not 0 <= expected_revision < _MAX_REVISION
            or not 0 <= next_revision <= _MAX_REVISION):
        raise ValueError("Invalid journal revision")
    before = _read(previous_json)
    after = _read(proposed_json)
    prior_ids = _order_ids(before)
    next_ids = _order_ids(after)
    checks = {
        "revision_contiguous": next_revision == expected_revision + 1,
        "source_identity_unchanged": _canonical(before["identity"]) == _canonical(after["identity"]),
        "actions_append_only": _prefix(before["actions"], after["actions"]),
        "actions_advanced": len(after["actions"]) > len(before["actions"]),
        "events_append_only": _prefix(before["events"], after["events"]),
        "order_ids_valid_and_unique": prior_ids is not None and next_ids is not None,
        "order_ids_retained_in_order": (
            prior_ids is not None and next_ids is not None
            and len(next_ids) >= len(prior_ids)
            and next_ids[:len(prior_ids)] == prior_ids
        ),
    }
    digest = hashlib.sha256(_canonical({
        "schema": "paper-journal-continuity-v1",
        "previous": before, "proposed": after,
        "expected_revision": expected_revision, "next_revision": next_revision,
    }).encode("ascii")).hexdigest()
    return {
        "schema": "paper-journal-continuity-v1",
        "status": "HOLD_RECONCILIATION",
        "assumption_checks_pass": all(checks.values()),
        "checks": checks,
        "failed_checks": [name for name, passed in checks.items() if not passed],
        "review_sha256": digest,
        "source_authenticated": False,
        "replay_verified": False,
        "journal_transaction_verified": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
        "warning": (
            "Untrusted snapshot continuity is not deterministic replay, "
            "broker evidence, owner approval, or permission to place an order."
        ),
    }
