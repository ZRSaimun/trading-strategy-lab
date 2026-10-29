"""Bounded, explicit, historical one-minute adapter. No live polling or fallback symbols."""
import asyncio
import csv
from email.utils import format_datetime, parsedate_to_datetime
import hashlib
import io
import json
import math
import re
from datetime import datetime, timezone
import httpx
from ..market import parse_csv

ENDPOINT='https://api.twelvedata.com/time_series'
MAPPINGS={'XAUUSD-TD':{'symbol':'XAU/USD','name':'Gold · Twelve Data XAU/USD','volume_type':'none'}}
MAX_BYTES=3_000_000
# httpx's per-read timeout resets for each arriving chunk. Bound the entire
# optional provider transaction, including response headers and body streaming.
MAX_REQUEST_SECONDS=30

def _credit_header_observation(headers):
    """Sanitize provider quota headers; never log or return arbitrary headers.

    Header counters describe provider-account usage in a quota window, NOT
    the cost of this request, daily SQLite reservations, or plan entitlement.
    Missing headers remain an explicit review blocker; malformed/duplicate
    headers are rejected instead of silently accepted.
    """
    counters = []
    for name in ('api-credits-used', 'api-credits-left'):
        values = headers.get_list(name)
        if not values:
            counters.append(None)
            continue
        if len(values) != 1 or re.fullmatch(r'[0-9]{1,10}', values[0]) is None:
            raise ValueError('Invalid provider credit header')
        count = int(values[0])
        if count > 1_000_000_000:
            raise ValueError('Provider credit header exceeds safe bound')
        counters.append(count)
    used, left = counters
    if (used is None) != (left is None):
        raise ValueError('Incomplete provider credit header pair')
    if used is not None and (used == 0 or used + left > 1_000_000_000):
        raise ValueError('Inconsistent provider credit header counters')
    return {
        'status': 'MISSING_REVIEW_REQUIRED' if used is None else 'OBSERVED_UNVERIFIED',
        'api_credits_used': used,
        'api_credits_left': left,
        'quota_window_verified': False,
        'account_usage_reconciled': False,
    }

def _validate_http_cache_headers(headers):
    """Reject ambiguous Date/Age claims without treating them as feed freshness.

    Date and Age can be supplied by proxies or caches, are not signed vendor
    timestamps, and cannot establish a completed candle's issue time. Missing
    headers remain acceptable for a historical import. Malformed/duplicate
    claims must not be silently ignored.
    """
    dates = headers.get_list('date')
    ages = headers.get_list('age')
    if len(dates) > 1 or len(ages) > 1:
        raise ValueError('Duplicate provider cache header')
    if dates:
        try:
            parsed = parsedate_to_datetime(dates[0])
            if (parsed.tzinfo is None or parsed.utcoffset().total_seconds() != 0
                    or format_datetime(parsed.astimezone(timezone.utc), usegmt=True) != dates[0]):
                raise ValueError('Noncanonical HTTP Date')
        except (ValueError, TypeError, OverflowError):
            raise ValueError('Invalid provider HTTP Date') from None
    if ages:
        if (re.fullmatch(r'(?:0|[1-9][0-9]{0,9})', ages[0]) is None
                or int(ages[0]) > 1_000_000_000):
            raise ValueError('Invalid provider HTTP Age')


def _reject_duplicate_response_keys(pairs):
    """Reject ambiguous vendor JSON before normalizing or archiving it."""
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('Duplicate provider JSON key')
        result[key]=value
    return result

def _reject_non_scalar_json_strings(value):
    """Reject isolated UTF-16 surrogate escapes anywhere in provider JSON.

    Python's JSON decoder permits unpaired surrogate escapes even in ignored
    metadata and object keys. These cannot be safely re-encoded as UTF-8
    evidence. Valid escaped surrogate pairs are decoded to Unicode scalars.
    """
    pending = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if any(0xD800 <= ord(char) <= 0xDFFF for char in item):
                raise ValueError('Unpaired provider JSON surrogate')
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)


def _reject_nonstandard_response_constant(value):
    """NaN and Infinity are not valid JSON evidence."""
    raise ValueError('Nonstandard provider JSON constant')

def _reject_nonfinite_response_float(value):
    """JSON exponent overflow must not become Python infinity, even in ignored fields."""
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('Nonfinite provider JSON number')
    return number

class ProviderError(Exception):
    def __init__(self,message,status=502):
        super().__init__(message);self.status=status

def normalize(payload,instrument,now):
    # This function is also used without retrieve(); never allow a malformed
    # or unhashable instrument to escape as an unhandled KeyError/TypeError.
    if type(instrument) is not str or instrument not in MAPPINGS:
        raise ProviderError('Unknown provider mapping; no instrument substitution.', 422)
    # Direct normalization callers do not necessarily pass through retrieve().
    # NaN would make every completed-bar comparison false, while +Infinity
    # would silently admit future candles. Never trust a caller-supplied
    # observation clock without the same finite UTC checks as retrieve().
    if type(now) not in (int, float):
        raise ProviderError('Invalid UTC observation timestamp; no data imported.', 422)
    try:
        if not math.isfinite(now) or now < 60:
            raise ValueError('Invalid UTC observation clock')
        datetime.fromtimestamp(now, timezone.utc)
    except (OverflowError, OSError, ValueError):
        raise ProviderError('Invalid UTC observation timestamp; no data imported.', 422) from None
    expected=MAPPINGS[instrument]['symbol']
    if not isinstance(payload,dict) or payload.get('status')!='ok':
        code=payload.get('code') if isinstance(payload,dict) else None
        if code in (401,403):raise ProviderError('Provider rejected the credential or entitlement. Check your account; no data imported.',403)
        if code==429:raise ProviderError('Provider quota exceeded. No data imported.',429)
        raise ProviderError('Provider returned an error. No data imported.')
    meta=payload.get('meta',{})
    if not isinstance(meta,dict) or meta.get('symbol')!=expected or meta.get('interval')!='1min' or meta.get('exchange_timezone')!='UTC':
        raise ProviderError('Provider metadata does not match the exact requested symbol, interval and UTC timezone.')
    values=payload.get('values')
    if not isinstance(values,list) or not 1<=len(values)<=5000:
        raise ProviderError('Provider returned no candles or exceeded the 5,000-candle limit.')
    normalized=[]
    try:
        for value in values:
            # Explicitly use only declared fields; provider extra fields cannot leak secrets into storage.
            # strptime accepts non-padded and even some Unicode-digit fields.
            # A provider minute must have one canonical ASCII UTC spelling;
            # otherwise normalization would silently erase source ambiguity.
            timestamp_text=value['datetime']
            if (type(timestamp_text) is not str or
                    re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2} [0-9]{2}:[0-9]{2}:[0-9]{2}', timestamp_text) is None):
                raise ValueError('Noncanonical provider UTC minute timestamp')
            dt=datetime.strptime(timestamp_text,'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
            if dt.second:raise ValueError('Minute alignment')
            if dt.timestamp()+60>now:continue  # incomplete or future candles are ineligible
            # JSON booleans are valid Python numbers (float(True) == 1.0).
            # Do not silently turn a provider's true/false into a Gold quote.
            # Preserve ordinary JSON decimal strings and numeric scalars.
            for field in ('open','high','low','close'):
                if type(value[field]) not in (str, int, float):
                    raise ValueError('Non-numeric provider OHLC scalar type')
            normalized.append({'time':dt.isoformat(),**{k:value[k] for k in ('open','high','low','close')}})
        normalized.sort(key=lambda r:r['time'])
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['time','open','high','low','close']);writer.writeheader();writer.writerows(normalized)
        rows=parse_csv(stream.getvalue())
        # Generic OHLC validation permits negative prices (some futures can
        # trade below zero). This mapping is spot XAU/USD, where zero or
        # negative quotes are not meaningful observations. Do not invent a
        # price floor or silently clamp a provider-supplied value.
        if expected == 'XAU/USD' and any(
            row[field] <= 0 for row in rows
            for field in ('open', 'high', 'low', 'close')
        ):
            raise ValueError('Nonpositive spot Gold OHLC')
    except (ValueError,TypeError,KeyError,csv.Error):
        # csv.DictReader enforces its own field-size limit. A bounded JSON
        # response can still contain a single overlong OHLC field, which must
        # fail closed rather than escape as an unhandled server exception.
        raise ProviderError('Invalid, duplicate or incomplete provider candles; no data imported.') from None
    archive={'meta':{'symbol':expected,'interval':'1min','exchange_timezone':'UTC'},'values':normalized}
    return rows,json.dumps(archive,separators=(',',':')).encode()

async def retrieve(key,instrument,limit,end,now,transport=None, *, include_wire_evidence=False):
    # Fail before a potentially chargeable request if a direct caller passes a
    # malformed credential. Never include its bytes in errors or diagnostics.
    # The official API key is an opaque printable ASCII token, not a URL value.
    if (type(key) is not str or not 1 <= len(key) <= 512
            or any(not 33 <= ord(ch) <= 126 for ch in key)):
        raise ProviderError('Invalid provider credential shape; no provider call.', 422)
    if type(instrument) is not str or instrument not in MAPPINGS:
        raise ProviderError('Unknown provider mapping; no instrument substitution.',422)
    if type(limit) is not int or not 1<=limit<=5000:
        raise ProviderError('Request requires an integer count of 1–5,000 candles.',422)
    if type(include_wire_evidence) is not bool:
        raise ProviderError('Invalid wire evidence mode.',422)
    # Validate caller-controlled boundaries BEFORE constructing a paid request.
    # bool is an int in Python, and nonfinite/out-of-range values can otherwise
    # raise unsanitized exceptions or silently distort the requested UTC window.
    if type(end) not in (int,float) or type(now) not in (int,float):
        raise ProviderError('Invalid UTC request timestamp; no provider call.',422)
    try:
        if not math.isfinite(end) or not math.isfinite(now):
            raise ValueError('Nonfinite UTC boundary')
        end_date = datetime.fromtimestamp(end,timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
        datetime.fromtimestamp(now,timezone.utc)
    except (OverflowError,OSError,ValueError):
        raise ProviderError('Invalid UTC request timestamp; no provider call.',422) from None
    # A direct adapter caller must not spend a credit on an impossible or
    # unfinished historical window. The HTTP route also enforces this gate,
    # but offline callers and prospective reviews invoke retrieve directly.
    # Fractional epoch seconds remain supported; the requested end is never
    # rounded forward into a candle that has not yet closed.
    if end < 0 or now < 60 or end > now - 60:
        raise ProviderError('Historical request must end at a completed UTC candle boundary; no provider call.',422)
    # Key goes in the official Authorization header, never URL/query/log output.
    params={'symbol':MAPPINGS[instrument]['symbol'],'interval':'1min','timezone':'UTC','order':'ASC','outputsize':str(limit),
            'end_date':end_date}
    try:
        async with asyncio.timeout(MAX_REQUEST_SECONDS), httpx.AsyncClient(timeout=20,follow_redirects=False,transport=transport,trust_env=False) as client:
            async with client.stream('GET',ENDPOINT,params=params,headers={'Authorization':'apikey '+key, 'Accept-Encoding':'identity'}) as response:
                if response.status_code in (401,403):raise ProviderError('Provider rejected the credential or entitlement.',403)
                if response.status_code==429:raise ProviderError('Provider quota exceeded.',429)
                if response.status_code!=200:raise ProviderError('Provider request failed; no data imported.')
                credit_headers = _credit_header_observation(response.headers) if include_wire_evidence else None
                _validate_http_cache_headers(response.headers)
                # A 200 response must represent the complete JSON entity, not a
                # claimed byte-range fragment. A valid-looking JSON body with a
                # Content-Range claim is ambiguous provenance and is quarantined.
                if response.headers.get_list('content-range'):
                    raise ProviderError('Unexpected provider partial-content claim; no data imported.')
                # A successful historical JSON endpoint must not explicitly
                # identify its response as HTML, plain text or another media
                # type. Keep missing Content-Type compatible with legacy
                # mock transports, but reject conflicting/ambiguous claims.
                media_types = response.headers.get_list('content-type')
                if (len(media_types) > 1 or
                        (media_types and re.fullmatch(
                            r'application/json(?:\s*;\s*charset\s*=\s*(?:utf-8|"utf-8"))?',
                            media_types[0].strip(), re.IGNORECASE) is None)):
                    raise ProviderError('Unsupported provider response media type; no data imported.')
                # Ask for identity encoding and reject compressed replies even if
                # the provider ignores the request. aiter_bytes() transparently
                # decompresses, potentially allocating an oversized chunk before
                # the cumulative limit can be enforced.
                encodings = response.headers.get_list('content-encoding')
                if (len(encodings) > 1 or
                        (encodings and encodings[0].strip().lower() != 'identity')):
                    raise ProviderError('Unsupported provider response encoding; no data imported.')
                lengths = response.headers.get_list('content-length')
                if (len(lengths) > 1 or
                        (lengths and (re.fullmatch(r'[0-9]{1,8}', lengths[0]) is None
                                      or int(lengths[0]) > MAX_BYTES))):
                    raise ProviderError('Invalid or oversized provider response length; no data imported.')
                # A Content-Length header is a claim about the exact entity
                # body size, not just an upper bound. Reject conflicting
                # framing and incomplete/overlong responses before JSON parse.
                # Transfer-Encoding without Content-Length remains supported
                # (HTTP/1.1 chunked transfer has no declared entity length).
                transfer_encodings = response.headers.get_list('transfer-encoding')
                if lengths and transfer_encodings:
                    raise ProviderError('Conflicting provider response framing; no data imported.')
                # The HTTP client handles transfer chunk framing, but other
                # transfer codings may change entity bytes before our bound
                # and digest checks. Accept only one explicit 'chunked' value.
                if (len(transfer_encodings) > 1 or
                        (transfer_encodings and transfer_encodings[0].strip().lower() != 'chunked')):
                    raise ProviderError('Unsupported provider transfer encoding; no data imported.')
                declared_length = int(lengths[0]) if lengths else None
                raw=bytearray()
                if response.is_stream_consumed and transport is not None:
                    # Injected mock transports may return an already-buffered
                    # Response. It cannot be streamed again; still bound it.
                    buffered = response.content
                    if len(buffered) > MAX_BYTES:
                        raise ProviderError('Provider response exceeded the safe size limit.')
                    raw.extend(buffered)
                else:
                    async for chunk in response.aiter_raw(chunk_size=65536):
                        if len(chunk) > MAX_BYTES - len(raw):
                            raise ProviderError('Provider response exceeded the safe size limit.')
                        raw.extend(chunk)
                if declared_length is not None and len(raw) != declared_length:
                    raise ProviderError('Provider response length mismatch; no data imported.')
                # json.loads(bytes) auto-detects UTF-16/32 and accepts a UTF-8 BOM.
                # Require strict UTF-8 JSON text so media-type and body-byte evidence agree.
                payload=json.loads(raw.decode('utf-8'),object_pairs_hook=_reject_duplicate_response_keys,
                                   parse_constant=_reject_nonstandard_response_constant,
                                   parse_float=_reject_nonfinite_response_float)
                _reject_non_scalar_json_strings(payload)
    except TimeoutError:
        raise ProviderError('Provider request exceeded cumulative deadline; no data imported.') from None
    except (httpx.HTTPError,ValueError,RecursionError):
        # Excessively nested but size-bounded JSON may raise RecursionError.
        # Fail closed with a sanitized provider error rather than a server 500.
        # Never return exception strings: HTTP client exceptions can contain request details.
        raise ProviderError('Provider request failed or returned invalid JSON; no data imported.') from None
    rows,archive=normalize(payload,instrument,now)
    # A provider must not expand past the requested boundary or requested count.
    if len(rows)>limit or any(r['time']>end for r in rows):
        raise ProviderError('Provider returned candles outside the requested boundary; no data imported.')
    if include_wire_evidence:
        # This is the HTTP-client-DECODED response body, not TLS wire bytes.
        # A digest detects accidental changes but is NOT a vendor signature.
        return rows,archive,{
            'decoded_http_body_sha256': hashlib.sha256(raw).hexdigest(),
            'decoded_http_body_bytes': len(raw),
            'normalized_snapshot_sha256': hashlib.sha256(archive).hexdigest(),
            'http_status': 200,
            'provider_credit_header_observation': credit_headers,
        }
    return rows,archive
