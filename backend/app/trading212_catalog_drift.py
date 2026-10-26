"""Offline drift review of two already-reconciled Trading 212 equity catalogs.

Never connects to a broker, asserts account identity, establishes data rights,
interprets market hours, or enables trading. Differences are observations only.
"""
from __future__ import annotations

from app.trading212_instrument_catalog import (
    InstrumentCatalogError, _utc, reconcile_trading212_instrument_catalog,
)


def _metadata(items: list[dict], exchanges: list[dict]) -> dict[str, tuple]:
    # The upstream catalog validator has checked all schedule references and
    # uniqueness. Include BOTH nested schedule ID and its parent exchange ID:
    # they are distinct in the official Trading 212 OpenAPI schema.
    schedule_exchanges = {
        schedule["id"]: exchange["id"]
        for exchange in exchanges for schedule in exchange["workingSchedules"]
    }
    return {
        item["ticker"]: (
            item["type"], item["currencyCode"], item["workingScheduleId"],
            schedule_exchanges[item["workingScheduleId"]],
            item["name"], item["shortName"], item["extendedHours"],
            item["maxOpenQuantity"],
        )
        for item in items
    }


def compare_trading212_catalogs(
    previous_instruments: dict, previous_exchanges: dict,
    current_instruments: dict, current_exchanges: dict, *,
    declared_account_scope_sha256: str,
    requested_tickers: list[str] | None = None,
) -> dict:
    """Compare two validated metadata pairs; return bounded aggregate drift.

    Receipt chronology is local clock evidence, not an authenticated broker
    timestamp. A common caller-declared scope is NOT proof of same account.
    """
    kwargs = {
        "declared_account_scope_sha256": declared_account_scope_sha256,
        "requested_tickers": requested_tickers,
    }
    previous = reconcile_trading212_instrument_catalog(
        previous_instruments, previous_exchanges, **kwargs,
    )
    current = reconcile_trading212_instrument_catalog(
        current_instruments, current_exchanges, **kwargs,
    )
    if (previous["environment"] != current["environment"]
            or previous["account_type_declared"] != current["account_type_declared"]):
        raise InstrumentCatalogError("Catalog snapshots have incompatible declared scope")

    # Reject overlapping local receipt windows rather than implying which
    # provider snapshot was newer. Both pairs have already passed UTC checks.
    previous_end = max(
        _utc(previous_instruments["received_at_utc"]),
        _utc(previous_exchanges["received_at_utc"]),
    )
    current_start = min(
        _utc(current_instruments["received_at_utc"]),
        _utc(current_exchanges["received_at_utc"]),
    )
    if current_start <= previous_end:
        raise InstrumentCatalogError("Catalog receipt windows overlap or reverse")

    before = _metadata(previous_instruments["data"], previous_exchanges["data"])
    after = _metadata(current_instruments["data"], current_exchanges["data"])
    before_keys, after_keys = set(before), set(after)
    shared = before_keys & after_keys
    changed = {ticker for ticker in shared if before[ticker] != after[ticker]}
    added = after_keys - before_keys
    removed = before_keys - after_keys

    # Selected output is restricted to at most 25 explicit tickers by the
    # upstream validator. Never emit the full accessible instrument list.
    prev_selected = {r["ticker"]: r for r in previous["requested"]}
    curr_selected = {r["ticker"]: r for r in current["requested"]}
    selected = []
    for ticker in requested_tickers or []:
        if ticker in added:
            change = "ADDED_TO_DECLARED_CATALOG"
        elif ticker in removed:
            change = "REMOVED_FROM_DECLARED_CATALOG"
        elif ticker in changed:
            change = "DECLARED_METADATA_CHANGED"
        elif ticker in shared:
            change = "NO_DECLARED_METADATA_CHANGE"
        else:
            change = "ABSENT_IN_BOTH"
        selected.append({
            "ticker": ticker, "change": change,
            "previous": prev_selected.get(ticker),
            "current": curr_selected.get(ticker),
        })

    digest_changed = previous["catalog_sha256"] != current["catalog_sha256"]
    # The catalog digest also includes exchange names and schedules. Thus a
    # digest change without per-ticker changes may be exchange-only drift.
    changed_fields = (
        "type", "currency", "working_schedule_id", "exchange_id",
        "name", "short_name", "extended_hours", "max_open_quantity",
    )
    field_changes = {
        field: sum(before[t][i] != after[t][i] for t in changed)
        for i, field in enumerate(changed_fields)
    }
    requires_review = bool(added or removed or changed or digest_changed)
    return {
        "result": "OFFLINE_DECLARED_EQUITY_CATALOG_DRIFT_ONLY",
        "review": "REVIEW_REQUIRED" if requires_review else "NO_DECLARED_CHANGE_OBSERVED",
        "provider": "Trading 212",
        "environment": previous["environment"],
        "account_type_declared": previous["account_type_declared"],
        "previous_catalog_sha256": previous["catalog_sha256"],
        "current_catalog_sha256": current["catalog_sha256"],
        "catalog_digest_changed": digest_changed,
        "previous_instruments_count": len(before),
        "current_instruments_count": len(after),
        "shared_instruments_count": len(shared),
        "added_instruments_count": len(added),
        "removed_instruments_count": len(removed),
        "changed_shared_instruments_count": len(changed),
        "changed_field_counts": field_changes,
        "other_catalog_metadata_may_have_changed": digest_changed,
        "requested": selected,
        "same_account_verified": False,
        "provider_entitlement_verified": False,
        "source_authenticity_verified": False,
        "market_calendar_verified": False,
        "market_data_feed": False,
        "cfd_supported": False,
        "may_execute_order": False,
    }
