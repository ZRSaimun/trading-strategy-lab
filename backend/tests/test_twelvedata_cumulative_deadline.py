"""Synthetic zero-network regressions for the total Twelve Data HTTP deadline."""
import asyncio

import httpx
import pytest

import app.providers.twelvedata as provider

T = 1790000040


class SlowChunks(httpx.AsyncByteStream):
    async def __aiter__(self):
        # One body chunk is enough to prove that a per-read timeout alone
        # does not enforce the cumulative deadline.
        await asyncio.sleep(0.05)
        yield b'{"status":"ok"}'

    async def aclose(self):
        pass


def _retrieve(transport):
    return asyncio.run(provider.retrieve(
        "synthetic-only-secret", "XAUUSD-TD", 1, T, T + 120,
        transport=transport, include_wire_evidence=True,
    ))


def test_slow_response_headers_exceed_total_deadline(monkeypatch):
    monkeypatch.setattr(provider, "MAX_REQUEST_SECONDS", 0.01)
    calls = []

    async def handler(request):
        calls.append(request)
        await asyncio.sleep(0.05)
        return httpx.Response(200, content=b'{"status":"ok"}')

    with pytest.raises(provider.ProviderError, match="cumulative deadline") as exc:
        _retrieve(httpx.MockTransport(handler))
    assert exc.value.status == 502
    assert len(calls) == 1
    assert "synthetic-only-secret" not in str(exc.value)


def test_trickling_response_body_exceeds_total_deadline(monkeypatch):
    monkeypatch.setattr(provider, "MAX_REQUEST_SECONDS", 0.01)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, stream=SlowChunks())

    with pytest.raises(provider.ProviderError, match="cumulative deadline") as exc:
        _retrieve(httpx.MockTransport(handler))
    assert exc.value.status == 502
    assert len(calls) == 1
    assert "synthetic-only-secret" not in str(exc.value)
