"""Synthetic-only shape tests. Never contact Trading 212."""
from copy import deepcopy

import pytest

from app.trading212_demo_metadata_schema import (
    DemoMetadataSchemaError, validate_demo_metadata_shape,
)


def instrument(**changes):
    row = dict(ticker="AAPL_US_EQ", currencyCode="USD", type="STOCK",
               workingScheduleId=1, maxOpenQuantity=100.0,
               extendedHours=False, name="Example Equity", shortName="Example")
    row.update(changes)
    return row


def exchange(**changes):
    row = dict(id=1, name="Example Exchange", workingSchedules=[])
    row.update(changes)
    return row


def test_valid_and_unchanged():
    data = [instrument()]
    original = deepcopy(data)
    assert validate_demo_metadata_shape("instruments", data) == 1
    assert validate_demo_metadata_shape("exchanges", [exchange()]) == 1
    assert data == original
    assert validate_demo_metadata_shape("instruments", []) == 0


@pytest.mark.parametrize("endpoint,payload", [
    ("orders", []), ("instruments", {}), ("exchanges", [0]),
    ("instruments", [instrument(ticker="INVALID/PAIR")]),
    ("instruments", [instrument(ticker="AAPL_US_EQ"), instrument()]),
    ("instruments", [instrument(currencyCode="usd")]),
    ("instruments", [instrument(type="CFD")]),
    ("instruments", [instrument(type=[])]),
    ("instruments", [instrument(workingScheduleId=True)]),
    ("instruments", [instrument(workingScheduleId=-1)]),
    ("instruments", [instrument(maxOpenQuantity=float("inf"))]),
    ("instruments", [instrument(maxOpenQuantity=float("nan"))]),
    ("instruments", [instrument(maxOpenQuantity=-1)]),
    ("instruments", [instrument(maxOpenQuantity=True)]),
    ("instruments", [instrument(maxOpenQuantity=10**1000)]),
    ("instruments", [instrument(extendedHours=1)]),
    ("instruments", [instrument(name="\nsecret")]),
    ("instruments", [instrument(shortName="")]),
    ("exchanges", [exchange(id=True)]),
    ("exchanges", [exchange(id=-1)]),
    ("exchanges", [exchange(), exchange()]),
    ("exchanges", [exchange(workingSchedules={})]),
    ("exchanges", [exchange(workingSchedules=["bad"])]),
    ("exchanges", [exchange(name="\x00")]),
    ("exchanges", [exchange(workingSchedules=[{}] * 1001)]),
])
def test_reject_bad_shape(endpoint, payload):
    with pytest.raises(DemoMetadataSchemaError) as exc:
        validate_demo_metadata_shape(endpoint, payload)
    assert "AAPL" not in str(exc.value)


def test_limits_and_bool_rejection():
    with pytest.raises(DemoMetadataSchemaError):
        validate_demo_metadata_shape("instruments", [None] * 50_001)
    with pytest.raises(DemoMetadataSchemaError):
        validate_demo_metadata_shape("exchanges", [None] * 2_001)
