"""Bounded, explicit, historical one-minute adapter. No live polling or fallback symbols."""
import csv
import hashlib
import io
import json
from datetime import datetime, timezone
import httpx
from ..market import parse_csv

ENDPOINT='https://api.twelvedata.com/time_series'
MAPPINGS={'XAUUSD-TD':{'symbol':'XAU/USD','name':'Gold · Twelve Data XAU/USD','volume_type':'none'}}
MAX_BYTES=3_000_000

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
            dt=datetime.strptime(value['datetime'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
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
    if not 1<=limit<=5000:raise ProviderError('Request requires 1–5,000 candles.',422)
    if type(include_wire_evidence) is not bool:
        raise ProviderError('Invalid wire evidence mode.',422)
    # Key goes in the official Authorization header, never URL/query/log output.
    params={'symbol':MAPPINGS[instrument]['symbol'],'interval':'1min','timezone':'UTC','order':'ASC','outputsize':str(limit),
            'end_date':datetime.fromtimestamp(end,timezone.utc).strftime('%Y-%m-%d %H:%M:%S')}
    try:
        async with httpx.AsyncClient(timeout=20,follow_redirects=False,transport=transport,trust_env=False) as client:
            async with client.stream('GET',ENDPOINT,params=params,headers={'Authorization':'apikey '+key}) as response:
                if response.status_code in (401,403):raise ProviderError('Provider rejected the credential or entitlement.',403)
                if response.status_code==429:raise ProviderError('Provider quota exceeded.',429)
                if response.status_code!=200:raise ProviderError('Provider request failed; no data imported.')
                raw=bytearray()
                async for chunk in response.aiter_bytes():
                    raw.extend(chunk)
                    if len(raw)>MAX_BYTES:raise ProviderError('Provider response exceeded the safe size limit.')
                payload=json.loads(raw,object_pairs_hook=_reject_duplicate_response_keys,
                                   parse_constant=_reject_nonstandard_response_constant)
    except (httpx.HTTPError,ValueError):
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
        }
    return rows,archive
