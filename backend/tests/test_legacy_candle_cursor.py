"""Legacy chart pagination must not truncate an aggregate at an arbitrary minute."""
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app import main
from app.db import Base


def utc(year, month, day):
    return int(datetime(year, month, day, tzinfo=timezone.utc).timestamp())


@pytest.fixture
def client(monkeypatch):
    # Disposable database; never touches the owner's historical or cloud data.
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    monkeypatch.setattr(main, "Session", sessionmaker(bind=engine))
    main.app.dependency_overrides[main.owner] = lambda: "test-owner"
    try:
        yield TestClient(main.app)
    finally:
        main.app.dependency_overrides.pop(main.owner, None)
        engine.dispose()


@pytest.mark.parametrize(
    ("timeframe", "before"),
    [
        ("5m", 60),                         # Inside a five-minute candle
        ("1H", 3600 + 60),                  # Inside an hourly candle
        ("1W", utc(2026, 10, 19) + 60),    # Monday plus one minute
        ("1M", utc(2026, 10, 2)),          # Not the first day of the month
        ("1m", -60),                        # Negative timestamp
        ("1m", 10**20),                     # Outside datetime's supported range
    ],
)
def test_legacy_endpoint_rejects_unsafe_before(client, timeframe, before):
    response = client.get(
        "/api/candles/XAUUSD-IMPORT",
        params={"timeframe": timeframe, "before": before},
    )
    assert response.status_code == 422, response.text
    assert "complete timeframe bucket boundary" in response.json()["detail"]


@pytest.mark.parametrize(
    ("timeframe", "before"),
    [
        ("1m", 60),
        ("5m", 300),
        ("1H", 3600),
        ("1W", utc(2026, 10, 19)),
        ("1M", utc(2026, 10, 1)),
    ],
)
def test_legacy_endpoint_accepts_exact_utc_boundaries(client, timeframe, before):
    response = client.get(
        "/api/candles/XAUUSD-IMPORT",
        params={"timeframe": timeframe, "before": before},
    )
    assert response.status_code == 200, response.text
    assert response.json()["quality"]["state"] == "NO DATA"
