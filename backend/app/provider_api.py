import hashlib
import json
import os
import stat
import threading
import time
from pathlib import Path
from typing import Literal
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import delete
from .db import Session,Candle,Record
from .providers import vault
from .providers.twelvedata import retrieve,MAPPINGS,ProviderError
from .completed_candle_quality import assess_completed_m1
from .provider_snapshot import verify_normalized_snapshot

router=APIRouter()
_import_lock=threading.Lock()
_last_attempt=0.0

def free_only():
    # Unknown values fail closed. Removing a flag must never enable paid access.
    return os.getenv('FREE_ONLY', 'true').strip().lower() != 'false'


def attach(owner,audit):
    @router.get('/api/providers')
    def status(auth=Depends(owner)):
        ready=vault.configured()
        enabled=not free_only() and os.getenv('TWELVEDATA_ENABLED','false').lower()=='true'
        return {'deployment':'private-server','provider':'twelvedata','credential_configured':ready,'enabled':enabled,'free_only':free_only(),
                'state':'READY FOR MANUAL IMPORT' if ready and enabled else 'NOT CONNECTED',
                'rights_confirmation_scope':'owner_assertion_only','provider_instrument_entitlement_verified':False,
                'retention_rights_verified':False,'display_rights_verified':False,'non_display_rights_verified':False,
                'live':False,'automatic_requests':False,'mappings':[dict(id=k,**v) for k,v in MAPPINGS.items()],
                'limits':{'max_candles':5000,'min_request_seconds':60,'interval':'1min','mode':'historical only'},
                'message':'Manual historical imports only. Gold entitlement and internal display/non-display rights must be confirmed; Nasdaq mapping is not verified.'}

    class ImportRequest(BaseModel):
        model_config=ConfigDict(extra='forbid')
        instrument:Literal['XAUUSD-TD']
        limit:int=Field(default=1000,ge=1,le=5000)
        end:int=Field(ge=0)
        rights_confirmed:bool
        replace_confirmed:bool

    @router.post('/api/providers/twelvedata/import')
    async def import_history(body:ImportRequest,auth=Depends(owner)):
        global _last_attempt
        if free_only():raise HTTPException(409,'Free-only policy blocks this external data adapter; no request was made.')
        if os.getenv('TWELVEDATA_ENABLED','false').lower()!='true':raise HTTPException(409,'Provider is disabled; no request was made.')
        if not body.rights_confirmed or not body.replace_confirmed:raise HTTPException(422,'Confirm data rights and replacement of this provider series.')
        now=int(time.time())
        if body.end>now-60:raise HTTPException(422,'Choose a completed historical candle boundary.')
        try:key=vault.load_key()
        except vault.CredentialUnavailable:raise HTTPException(503,'Encrypted provider credential is not configured.') from None
        if not _import_lock.acquire(blocking=False):raise HTTPException(409,'Another import is in progress.')
        try:
            if time.monotonic()-_last_attempt<60:raise HTTPException(429,'Wait at least 60 seconds between provider requests.')
            request_started_monotonic=time.monotonic()
            _last_attempt=request_started_monotonic
            try:rows,archive=await retrieve(key,body.instrument,body.limit,body.end,now)
            except ProviderError as e:raise HTTPException(e.status,str(e)) from None
            # Wall clock identifies when the server received the response; monotonic
            # elapsed time measures the request independently of wall-clock changes.
            response_received_at=int(time.time())
            request_elapsed_ms=max(0,int((time.monotonic()-request_started_monotonic)*1000))
            # A vendor can return only unfinished rows (normalization then yields
            # an empty set), or a malformed normalized row. Never turn either
            # into a 500 or overwrite an existing research series.
            try:
                quality=assess_completed_m1(rows,response_received_at)
                # The content-addressed source snapshot must describe exactly the
                # rows about to replace the provider series, not merely hash cleanly.
                verify_normalized_snapshot(rows,archive,MAPPINGS[body.instrument]['symbol'])
            except (ValueError, OverflowError, OSError):
                raise HTTPException(502,'Provider returned no valid completed candle set; existing data unchanged.') from None
            digest=hashlib.sha256(archive).hexdigest()
            # Not web-served: archive is a vetted source-field snapshot, never a credential file.
            directory=Path(os.getenv('MARKET_ARCHIVE_DIR','./data/market-archive'))
            try:
                directory.mkdir(parents=True,exist_ok=True,mode=0o700)
                target=directory/(digest+'.json')
                if not target.exists():
                    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
                    with os.fdopen(fd,'wb') as f:f.write(archive)
                # A digest-shaped filename alone does not prove an existing
                # archive is intact. Verify exact bytes before replacing candles.
                # O_NOFOLLOW prevents accepting a symlink to an external file.
                fd=os.open(target,os.O_RDONLY|os.O_NOFOLLOW)
                with os.fdopen(fd,'rb') as f:
                    if not stat.S_ISREG(os.fstat(f.fileno()).st_mode):
                        raise OSError('Archive is not a regular file')
                    stored=f.read(len(archive)+1)
                if stored!=archive:
                    raise OSError('Archive content does not match source snapshot')
            except OSError:raise HTTPException(503,'Cannot verify provider archive; database unchanged.') from None
            source='Twelve Data · '+MAPPINGS[body.instrument]['symbol']+' · historical API (rights unverified)'
            manifest={'source':source,'provider':'twelvedata','provider_symbol':MAPPINGS[body.instrument]['symbol'],
                      'retrieved_at':now,'request_started_at':now,
                      'response_received_at':response_received_at,'request_elapsed_ms':request_elapsed_ms,
                      'receipt_clock':'server_wall_utc','elapsed_clock':'server_monotonic',
                      'sha256':digest,'hash_scope':'vetted source-field snapshot','volume_type':'none',
                      'rows':len(rows),'start':rows[0]['time'],'end':rows[-1]['time'],
                      'gaps':sum(b['time']-a['time']>60 for a,b in zip(rows,rows[1:])),
                      'quality':quality,
                      'rights_confirmed':True,'rights_confirmation_scope':'owner_assertion_only',
                      'provider_instrument_entitlement_verified':False,'retention_rights_verified':False,
                      'display_rights_verified':False,'non_display_rights_verified':False,
                      'live':False,'request_limit':body.limit,'request_end':body.end}
            with Session() as db:
                db.execute(delete(Candle).where(Candle.instrument==body.instrument))
                db.add_all([Candle(instrument=body.instrument,source=source,retrieved_at=now,**r) for r in rows])
                db.merge(Record(key='dataset:'+body.instrument,value=json.dumps(manifest)))
                audit(db,'provider.historical_import',{'instrument':body.instrument,**manifest});db.commit()
            return manifest
        finally:
            _import_lock.release()
    return router
