"""Actual private data readiness never implies broker or profitable-strategy readiness."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from app.db import Base, Candle
from app.bulk_import import metadata, datasets
from app.system_readiness import build_router, inspect_research_storage, readiness_report


def test_empty_is_research_only():
    doc = readiness_report({"legacy_candles":0,"ready_archive_datasets":0,
                            "declared_accepted_archive_candles":0})
    assert doc["state"] == "RESEARCH_ONLY"
    assert doc["automatic_live_trading_ready"] is False
    assert doc["paper_trading_state"] == "SIMULATION_ONLY"
    assert "research_data_available" in doc["blockers"]


def test_many_archives_still_not_certified_for_live_money():
    doc = readiness_report({"legacy_candles":5000,"ready_archive_datasets":27,
                            "declared_accepted_archive_candles":3780046})
    assert next(c["met"] for c in doc["checks"] if c["id"]=="archive_data_in_cloud")
    assert "broker_account_connected" in doc["blockers"]
    assert "out_of_sample_positive_edge" in doc["blockers"]
    assert "autonomous_live_order_path" in doc["blockers"]


def test_counts_include_ready_only_and_do_not_write():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread":False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    metadata.create_all(engine)
    with engine.begin() as con:
        con.execute(Candle.__table__.insert().values(
            instrument="XAUUSD-IMPORT",time=60,source="test",retrieved_at=60,
            open=1,high=2,low=0.5,close=1.5,volume=None))
        meta = dict(provider="HistData",instrument="NSXUSD-CFD",format="ascii",
                    utc_offset_minutes=-300,archive_sha256="a"*64,
                    archive_filename="data.zip",seen=3,accepted=3,rejected=0,
                    zero_volume=3,checkpoint_member=1,checkpoint_line=0)
        con.execute(datasets.insert(),[
            dict(meta,id="b"*64,state="READY"),
            dict(meta,id="c"*64,state="FAILED"),
        ])
    first = inspect_research_storage(engine)
    second = inspect_research_storage(engine)
    assert first == second
    assert first["legacy_candles"] == 1
    assert first["ready_archive_datasets"] == 1
    assert first["declared_accepted_archive_candles"] == 3
    assert first["archive_candle_count_independently_verified"] is False
    engine.dispose()


def test_owner_authentication_and_no_order_side_effect():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread":False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    metadata.create_all(engine)
    def owner(request:Request):
        if request.headers.get("X-Test-Owner") != "allowed":
            raise HTTPException(401,"Owner login required")
    app = FastAPI()
    app.include_router(build_router(owner,engine))
    client = TestClient(app)
    assert client.get("/api/system/readiness").status_code == 401
    response = client.get("/api/system/readiness",headers={"X-Test-Owner":"allowed"})
    assert response.status_code == 200
    assert response.json()["automatic_live_trading_ready"] is False
    assert client.post("/api/system/readiness",headers={"X-Test-Owner":"allowed"}).status_code == 405
    engine.dispose()
