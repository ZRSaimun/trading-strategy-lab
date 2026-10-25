"""Raw vendor-response ambiguity tests; entirely offline MockTransport."""
import asyncio
import json

import httpx
import pytest

from app.providers.twelvedata import ProviderError, retrieve


NOW = 1700001000
KEY = 'synthetic-key-not-a-credential'
PAYLOAD = {
    'status': 'ok',
    'meta': {'symbol': 'XAU/USD', 'interval': '1min', 'exchange_timezone': 'UTC'},
    'values': [{
        'datetime': '2023-11-14 22:14:00',
        'open': '2000', 'high': '2002', 'low': '1999', 'close': '2001',
    }],
}


def request_raw(raw):
    def handler(request):
        assert request.url.host == 'api.twelvedata.com'
        assert request.headers['Authorization'] == 'apikey ' + KEY
        return httpx.Response(200, content=raw, headers={'Content-Type': 'application/json'})

    return asyncio.run(retrieve(
        KEY, 'XAUUSD-TD', 5, NOW - 60, NOW, httpx.MockTransport(handler)
    ))


def test_unambiguous_raw_response_remains_accepted():
    rows, archive = request_raw(json.dumps(PAYLOAD).encode())
    assert len(rows) == 1
    assert rows[0]['close'] == 2001.0
    assert b'XAU/USD' in archive


@pytest.mark.parametrize('old,new', [
    (b'"status": "ok"', b'"status": "error", "status": "ok"'),
    (b'"symbol": "XAU/USD"', b'"symbol": "XAG/USD", "symbol": "XAU/USD"'),
    (b'"close": "2001"', b'"close": "9999", "close": "2001"'),
])
def test_raw_duplicate_keys_fail_before_normalization(old, new):
    raw = json.dumps(PAYLOAD).encode()
    assert old in raw
    with pytest.raises(ProviderError) as error:
        request_raw(raw.replace(old, new, 1))
    assert error.value.status == 502
    assert KEY not in str(error.value)


@pytest.mark.parametrize('constant', [b'NaN', b'Infinity', b'-Infinity'])
def test_raw_nonstandard_json_numbers_fail_closed(constant):
    raw = json.dumps(PAYLOAD).encode()
    assert b'"close": "2001"' in raw
    raw = raw.replace(b'"close": "2001"', b'"close": ' + constant, 1)
    with pytest.raises(ProviderError) as error:
        request_raw(raw)
    assert error.value.status == 502
    assert KEY not in str(error.value)
