"""Owner-only read-only trading research readiness checks.

Presence of bid-only archive candles never implies a live executable quote,
verified strategy profitability, or connected brokerage account.
"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, inspect, select
from sqlalchemy.exc import SQLAlchemyError
from .db import Candle
from .bulk_import import datasets as historical_datasets


def inspect_research_storage(engine):
    """Use dataset metadata counters, avoiding a multimillion-row candle scan."""
    with engine.connect() as connection:
        tables = inspect(connection)
        legacy = int(connection.scalar(select(func.count()).select_from(Candle.__table__)) or 0) if tables.has_table("candles") else 0
        if tables.has_table("historical_datasets") and tables.has_table("historical_candles"):
            row = connection.execute(select(
                func.count(), func.coalesce(func.sum(historical_datasets.c.accepted), 0)
            ).where(historical_datasets.c.state == "READY")).one()
            ready, accepted = int(row[0]), int(row[1])
        else:
            ready, accepted = 0, 0
    return {
        "legacy_candles": legacy,
        "ready_archive_datasets": ready,
        "declared_accepted_archive_candles": accepted,
        "archive_candle_count_independently_verified": False,
    }


def readiness_report(storage):
    have_archive = storage["ready_archive_datasets"] > 0 and storage["declared_accepted_archive_candles"] > 0
    have_data = have_archive or storage["legacy_candles"] > 0
    checks = [
        {"id": "research_data_available", "met": have_data,
         "detail": "Some historical research candles are stored on the server." if have_data else "Import authorized historical candles into the private database."},
        {"id": "archive_data_in_cloud", "met": have_archive,
         "detail": "READY isolated archive datasets are present." if have_archive else "Offline archive backups are not yet queryable in the private cloud database."},
        {"id": "real_time_executable_quotes", "met": False,
         "detail": "No independently verified live bid/ask market feed is integrated."},
        {"id": "broker_account_connected", "met": False,
         "detail": "No authenticated eligible demo or real brokerage connection is present."},
        {"id": "persistent_forward_paper_trading", "met": False,
         "detail": "Historical simulation exists, but unattended quote-driven prospective paper execution is not connected."},
        {"id": "out_of_sample_positive_edge", "met": False,
         "detail": "No independently validated prospective post-cost positive strategy edge is established."},
        {"id": "autonomous_live_order_path", "met": False,
         "detail": "Risk previews are non-executing and no authorized broker execution path is configured."},
    ]
    return {
        "state": "RESEARCH_ONLY",
        "automatic_live_trading_ready": False,
        "manual_broker_trading_certified_by_app": False,
        "paper_trading_state": "SIMULATION_ONLY",
        "research_storage": storage,
        "checks": checks,
        "blockers": [c["id"] for c in checks if not c["met"]],
        "disclosures": [
            "Historical bid-only candles cannot prove executable spreads, slippage, or actual trade fills.",
            "Trading 212 Public API covers Invest/Stocks ISA but not CFD order execution.",
            "No strategy profitability or future outcome is guaranteed.",
        ],
    }


def build_router(owner, engine):
    router = APIRouter(prefix="/api/system", tags=["System Readiness"])

    @router.get("/readiness")
    def readiness(auth=Depends(owner)):
        try:
            storage = inspect_research_storage(engine)
        except SQLAlchemyError:
            storage = {
                "legacy_candles": 0, "ready_archive_datasets": 0,
                "declared_accepted_archive_candles": 0,
                "archive_candle_count_independently_verified": False,
                "storage_status": "UNAVAILABLE",
            }
        return readiness_report(storage)

    return router
