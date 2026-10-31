"""Read-only, one-statement cross-store PAPER risk evidence preflight.

Correlates *unverified* persisted order intent, quote replay marker and
daily-loss latch. This is not an execution gate, broker authentication,
reservation, or replacement for authoritative account-wide reconciliation.
"""
from datetime import datetime, timezone
import hashlib
import json

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from .db import Record, Session
from .paper_daily_loss_breaker import PaperDailyLossBreaker, _decode as decode_loss
from .paper_order_intent_registry import _key as intent_key, _decode as decode_intent, _SHA
from .paper_quote_replay_store import PaperQuoteReplayStore, _decode as decode_quote, _MAX_MS


def _report(checks, reason):
    """Every possible outcome is a non-executable reconciliation hold."""
    return {
        "status": "HOLD_RECONCILIATION",
        "reason": reason,
        "checks": checks,
        "observations_coherent_unverified": bool(checks) and all(checks.values()),
        "broker_authenticated": False,
        "account_inventory_reconciled": False,
        "human_order_approval_verified": False,
        "may_execute_paper_order": False,
        "may_execute_real_order": False,
    }


class PaperRiskBundlePreflight:
    """Single SELECT snapshot; no network, credentials, writes or order sender.

    One SQL statement avoids mixing separately loaded revisions under PostgreSQL
    READ COMMITTED. It cannot establish that other orders, quotes or broker
    positions do not exist. Database errors and corrupt records fail closed.
    """

    def __init__(self, session_factory=Session):
        self.session_factory = session_factory

    def inspect(self, account_id, client_order_id, source, *, review_sha256,
                now_ms, max_quote_age_ms=3000, max_loss_age_ms=10000):
        if (type(now_ms) is not int or not 0 <= now_ms <= _MAX_MS
            or type(max_quote_age_ms) is not int or not 100 <= max_quote_age_ms <= 3000
            or type(max_loss_age_ms) is not int or not 100 <= max_loss_age_ms <= 10000):
            raise ValueError("Invalid trusted server time or bounded freshness policy")
        if not isinstance(review_sha256, str) or not _SHA.fullmatch(review_sha256):
            raise ValueError("Invalid reviewed-intent digest")
        if not isinstance(source, dict) or source.get("account_alias") != account_id:
            raise ValueError("Quote source and order account must match")
        try:
            day = datetime.fromtimestamp(now_ms / 1000, tz=timezone.utc).date().isoformat()
        except (ValueError, OverflowError, OSError) as exc:
            raise ValueError("Invalid UTC server date") from exc
        ikey, account_hash, order_hash = intent_key(account_id, client_order_id)
        lkey = PaperDailyLossBreaker._key(account_id, day)
        qkey = PaperQuoteReplayStore._key(source)
        owner_key = "paper-quote-journal-owner:" + qkey.split(":", 1)[1]
        keys = (ikey, lkey, qkey, owner_key)
        try:
            # Single statement, not four independent loads; no DB mutation.
            with self.session_factory() as db:
                records = dict(db.execute(
                    select(Record.key, Record.value).where(Record.key.in_(keys))
                ).all())
        except SQLAlchemyError:
            return _report({"storage_read_succeeded": False}, "STORAGE_UNAVAILABLE")

        checks = {
            "intent_present": ikey in records,
            "daily_loss_present": lkey in records,
            "quote_marker_present": qkey in records,
            "quote_source_not_bound_to_atomic_journal": owner_key not in records,
        }
        if not all((checks["intent_present"], checks["daily_loss_present"],
                    checks["quote_marker_present"])):
            return _report(checks, "INCOMPLETE_RISK_EVIDENCE")
        try:
            for key in (ikey, lkey, qkey):
                raw = records[key]
                if not isinstance(raw, str) or len(raw.encode("utf-8")) > 16384:
                    raise ValueError("Oversized stored evidence")
            intent = decode_intent(records[ikey], account_hash, order_hash)
            loss = decode_loss(records[lkey], expected_day=day)
            quote = decode_quote(records[qkey], qkey.split(":", 1)[1])
        except (ValueError, TypeError, OverflowError, RecursionError, UnicodeError):
            return _report({**checks, "stored_state_valid": False}, "CORRUPT_RISK_EVIDENCE")

        checks.update({
            "stored_state_valid": True,
            "intent_is_preview_only": intent["state"] == "PREVIEW_ONLY",
            "intent_digest_matches": intent["review_sha256"] == review_sha256,
            "intent_current": intent["created_ms"] <= now_ms < intent["expires_ms"],
            "daily_loss_observed": loss["revision"] > 0,
            "daily_loss_latch_clear_unverified": not loss["latched"],
            "daily_loss_observation_fresh": (
                loss["revision"] > 0 and loss["observed_ms"] <= now_ms
                and now_ms - loss["observed_ms"] <= max_loss_age_ms
            ),
            "quote_time_order_valid": (
                quote["observed_at_ms"] <= quote["received_at_ms"]
                <= quote["accepted_at_ms"] <= now_ms
            ),
            "quote_observation_fresh": (
                quote["observed_at_ms"] <= now_ms
                and now_ms - quote["observed_at_ms"] <= max_quote_age_ms
            ),
            "quote_transport_within_one_second": (
                quote["received_at_ms"] >= quote["observed_at_ms"]
                and quote["received_at_ms"] - quote["observed_at_ms"] <= 1000
            ),
        })
        # Diagnostic only: no raw aliases, IDs, quote prices or credentials.
        fingerprint = hashlib.sha256(json.dumps({
            "intent_key": ikey, "intent_revision": intent["revision"],
            "loss_key": lkey, "loss_revision": loss["revision"],
            "quote_key": qkey, "quote_revision": quote["revision"],
            "review_sha256": review_sha256,
        }, sort_keys=True, separators=(",", ":")).encode("ascii")).hexdigest()
        result = _report(checks, "UNAUTHENTICATED_EVIDENCE" if all(checks.values())
                         else "RISK_EVIDENCE_REQUIRES_RECONCILIATION")
        result["evidence_fingerprint_sha256"] = fingerprint
        return result
