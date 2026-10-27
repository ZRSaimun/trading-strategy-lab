"""Bounded, explicit, historical one-minute adapter. No live polling or fallback symbols."""
import csv
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

def _reject_duplicate_response_keys(pairs):
    """Reject ambiguous vendor JSON before normalizing or archiving it."""
    result={}
    for key,value in pairs:
        if key in result:
            raise ValueError('Duplicate provider JSON key')
        result[key]=value
    return result

def _reject_nonstandard_response_constant(value):
    """NaN and Infinity are not valid JSON evidence."""
    raise ValueError('Nonstandard provider JSON constant')

class ProviderError(Exception):
    def __init__(self,message,status=502):
        super().__init__(message);self.status=status

def normalize(payload,instrument,now):
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
            normalized.append({'time':dt.isoformat(),**{k:value[k] for k in ('open','high','low','close')}})
        normalized.sort(key=lambda r:r['time'])
        stream=io.StringIO();writer=csv.DictWriter(stream,fieldnames=['time','open','high','low','close']);writer.writeheader();writer.writerows(normalized)
        rows=parse_csv(stream.getvalue())
    except (ValueError,TypeError,KeyError):
        raise ProviderError('Invalid, duplicate or incomplete provider candles; no data imported.') from None
    archive={'meta':{'symbol':expected,'interval':'1min','exchange_timezone':'UTC'},'values':normalized}
    return rows,json.dumps(archive,separators=(',',':')).encode()

async def retrieve(key,instrument,limit,end,now,transport=None, *, include_wire_evidence=False):
    if instrument not in MAPPINGS:raise ProviderError('Unknown provider mapping; no instrument substitution.',422)
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
        async with httpx.AsyncClient(timeout=20,follow_redirects=False,transport=transport,trust_env=False) as client:
            async with client.stream('GET',ENDPOINT,params=params,headers={'Authorization':'apikey '+key, 'Accept-Encoding':'identity'}) as response:
                if response.status_code in (401,403):raise ProviderError('Provider rejected the credential or entitlement.',403)
                if response.status_code==429:raise ProviderError('Provider quota exceeded.',429)
                if response.status_code!=200:raise ProviderError('Provider request failed; no data imported.')
                credit_headers = _credit_header_observation(response.headers) if include_wire_evidence else None
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
                                   parse_constant=_reject_nonstandard_response_constant)
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
