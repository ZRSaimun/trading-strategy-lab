"""Scoped AI access. No provider credentials or execution capability is exposed."""
import hashlib
import json
import secrets
import time
import uuid
from typing import Literal
from collections import defaultdict, deque
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .db import Session, Record, Candle, Audit
from .registry import INSTRUMENTS
from .market import aggregate, TIMEFRAMES

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)
Scope=Literal['charts:read','drawings:write','notes:write','watchlist:write']
class TokenRequest(Strict):
    label:str=Field(min_length=1,max_length=80)
    scopes:list[Scope]=Field(min_length=1,max_length=4)
    expires_in_hours:int=Field(ge=1,le=720,default=24)
class Empty(Strict): pass
class Instrument(Strict):
    instrument:str=Field(min_length=1,max_length=80)
class CandlesArgs(Instrument):
    timeframe:str='5m'
    before:int|None=Field(default=None,ge=0)
    limit:int=Field(default=500,ge=1,le=2000)
class Point(Strict):
    time:int=Field(ge=0)
    price:float
class DrawingArgs(Instrument):
    id:str=Field(pattern=r'^[a-zA-Z0-9-]{1,80}$')
    kind:Literal['horizontal','trendline','rectangle','note']
    points:list[Point]=Field(min_length=1,max_length=2)
    text:str=Field(default='',max_length=500)
    version:int=Field(ge=0)
    idempotency_key:str=Field(pattern=r'^[a-zA-Z0-9-]{1,100}$')
class DeleteArgs(Instrument):
    id:str=Field(pattern=r'^[a-zA-Z0-9-]{1,80}$')
    version:int=Field(ge=1)
    idempotency_key:str=Field(pattern=r'^[a-zA-Z0-9-]{1,100}$')
class NoteArgs(Instrument):
    text:str=Field(min_length=1,max_length=5000)
    idempotency_key:str=Field(pattern=r'^[a-zA-Z0-9-]{1,100}$')
class WatchlistArgs(Strict):
    instruments:list[str]=Field(max_length=50)
    version:int=Field(ge=0)
    idempotency_key:str=Field(pattern=r'^[a-zA-Z0-9-]{1,100}$')

TOOLS={
 'list_instruments':(Empty,'charts:read','List exact instrument identities; disabled contracts remain labelled.'),
 'get_instrument_metadata':(Instrument,'charts:read','Get the exact registered instrument metadata.'),
 'get_candles':(CandlesArgs,'charts:read','Get bounded imported historical OHLCV candles and quality; never live executable quotes.'),
 'get_drawings':(Instrument,'charts:read','Get saved drawings with ownership, provenance and versions.'),
 'get_data_quality_status':(Instrument,'charts:read','Get source, coverage and freshness; missing data is NO DATA.'),
 'get_signal_history':(Empty,'charts:read','Get retained historical replay events; no live signal is inferred.'),
 'get_backtest_results':(Empty,'charts:read','Get saved simulator reports; these are not verified profitable strategies.'),
 'get_watchlist':(Empty,'charts:read','Get watchlist and revision needed for a controlled update.'),
 'create_chart_drawing':(DrawingArgs,'drawings:write','Create an explicitly AI-marked drawing. Version must be zero.'),
 'update_chart_drawing':(DrawingArgs,'drawings:write','Update a drawing using its exact current version and an idempotency key.'),
 'delete_chart_drawing':(DeleteArgs,'drawings:write','Delete a drawing with version check, idempotency and audit.'),
 'save_analysis_note':(NoteArgs,'notes:write','Save an AI research note, never an order or broker instruction.'),
 'update_watchlist':(WatchlistArgs,'watchlist:write','Replace watchlist with exact enabled instrument IDs and revision check.'),
}

def event(db,actor,action,detail):
    db.add(Audit(time=int(time.time()),actor=actor,action=action,detail=json.dumps(detail)))

def token_key(raw): return 'ai-token:'+hashlib.sha256(raw.encode()).hexdigest()
def authenticate(headers,db,lock=False):
    header=headers.get('authorization','')
    if not header.startswith('Bearer ') or len(header)>300: raise HTTPException(401,'AI bearer token required')
    stmt=select(Record).where(Record.key==token_key(header[7:]))
    if lock: stmt=stmt.with_for_update()
    rec=db.scalar(stmt)
    if not rec: raise HTTPException(401,'Invalid AI token')
    doc=json.loads(rec.value)
    if doc['revoked'] or doc['expires_at']<=time.time(): raise HTTPException(401,'Expired or revoked AI token')
    return rec,doc

# Per-process defensive request throttle; token state/expiry/revocation live in the database.
requests=defaultdict(deque)
def transport_auth(headers):
    with Session() as db: _,doc=authenticate(headers,db)
    now=time.monotonic();q=requests[doc['id']]
    while q and q[0]<now-60:q.popleft()
    if len(q)>=120:raise HTTPException(429,'AI request rate exceeded; retry after one minute')
    q.append(now)
    return doc

def check_instrument(i):
    if not any(r['id']==i and not r.get('disabled') for r in INSTRUMENTS): raise HTTPException(422,'Unknown or disabled instrument; no silent substitution')

def read_value(db,key,default=None):
    rec=db.get(Record,key);return json.loads(rec.value) if rec else default

def execute(name,arguments,headers):
    if name not in TOOLS:raise HTTPException(404,'Unknown AI tool')
    model,scope,_=TOOLS[name]
    args=model.model_validate(arguments)
    with Session() as db:
        _,token=authenticate(headers,db,lock=True)
        if scope not in token['scopes']:raise HTTPException(403,'AI token lacks required scope')
        actor='ai:'+token['id']
        if hasattr(args,'instrument'):check_instrument(args.instrument)
        idem=None;fingerprint=None
        if scope!='charts:read':
            encoded=json.dumps({'tool':name,'arguments':args.model_dump()},sort_keys=True,separators=(',',':'))
            fingerprint=hashlib.sha256(encoded.encode()).hexdigest()
            idem='ai-idem:'+token['id']+':'+hashlib.sha256(args.idempotency_key.encode()).hexdigest()
            prior=read_value(db,idem)
            if prior:
                if prior['fingerprint']!=fingerprint:raise HTTPException(409,'Idempotency key reused with different operation')
                return prior['result']
            count=db.scalar(select(func.count()).select_from(Record).where(Record.key.like('ai-idem:'+token['id']+':%')))
            if count>=10000:raise HTTPException(409,'Token write history limit reached; revoke and issue a fresh token')
        if name=='list_instruments':result=INSTRUMENTS
        elif name=='get_instrument_metadata': result=next(r for r in INSTRUMENTS if r['id']==args.instrument)
        elif name in ('get_candles','get_data_quality_status'):
            meta=read_value(db,'dataset:'+args.instrument)
            quality={'state':'NO DATA' if not meta else 'WAIT','live':False,'message':'Historical research only; no executable live quote','stale':True if not meta else time.time()-meta['end']>180}
            result={'dataset':meta,'quality':quality}
            if name=='get_candles':
                if args.timeframe not in TIMEFRAMES:raise HTTPException(422,'Unsupported timeframe')
                stmt=select(Candle).where(Candle.instrument==args.instrument)
                if args.before is not None:stmt=stmt.where(Candle.time<args.before)
                raw=db.scalars(stmt.order_by(Candle.time)).all()
                rows=aggregate([{k:getattr(b,k) for k in ('time','open','high','low','close','volume')} for b in raw],args.timeframe)
                result|={'candles':rows[-args.limit:],'has_more':len(rows)>args.limit}
        elif name=='get_drawings':result=[json.loads(r.value) for r in db.scalars(select(Record).where(Record.key.like('drawing:'+args.instrument+':%')))]
        elif name in ('get_signal_history','get_backtest_results'):
            kind='alert-events' if name=='get_signal_history' else 'backtests'
            rows=db.scalars(select(Record).where(Record.key.like('research:'+kind+':%')).limit(100)).all()
            result=[json.loads(r.value) for r in rows]
        elif name=='get_watchlist':result={'instruments':read_value(db,'watchlist',['XAUUSD-IMPORT','NDX-IMPORT']),'version':read_value(db,'watchlist-version',0)}
        elif name in ('create_chart_drawing','update_chart_drawing','delete_chart_drawing'):
            key='drawing:'+args.instrument+':'+args.id
            rec=db.scalar(select(Record).where(Record.key==key).with_for_update());prev=json.loads(rec.value) if rec else None
            if name=='create_chart_drawing' and (prev or args.version!=0):raise HTTPException(409,'Drawing already exists or invalid creation version')
            if name!='create_chart_drawing' and (not prev or prev['version']!=args.version):raise HTTPException(409,'Drawing changed or missing; reload its version')
            if name=='delete_chart_drawing':db.delete(rec);result={'deleted':True,'id':args.id}
            else:
                if len(args.points)!=(2 if args.kind in ('trendline','rectangle') else 1):raise HTTPException(422,'Incorrect coordinate count')
                result={k:v for k,v in args.model_dump().items() if k not in ('instrument','idempotency_key')}
                result|={'version':args.version+1,'owner':'owner','provenance':'ai','created_by':prev.get('created_by','manual') if prev else actor,'updated_by':actor,'updated_at':int(time.time())}
                db.merge(Record(key=key,value=json.dumps(result)))
            event(db,actor,'ai.'+name,{'instrument':args.instrument,'before':prev,'after':result})
        elif name=='save_analysis_note':
            result={'id':str(uuid.uuid4()),'instrument':args.instrument,'text':args.text,'created_at':int(time.time()),'provenance':'ai','actor':actor}
            db.add(Record(key='ai-note:'+result['id'],value=json.dumps(result)));event(db,actor,'ai.note.save',result)
        elif name=='update_watchlist':
            for i in args.instruments:check_instrument(i)
            rec=db.scalar(select(Record).where(Record.key=='watchlist-version').with_for_update())
            version=json.loads(rec.value) if rec else 0
            if args.version!=version:raise HTTPException(409,'Watchlist changed; reload its version')
            result={'instruments':list(dict.fromkeys(args.instruments)),'version':version+1}
            db.merge(Record(key='watchlist',value=json.dumps(result['instruments'])));db.merge(Record(key='watchlist-version',value=json.dumps(result['version'])))
            event(db,actor,'ai.watchlist.update',result)
        if idem:db.add(Record(key=idem,value=json.dumps({'fingerprint':fingerprint,'result':result})))
        try:db.commit()
        except IntegrityError:db.rollback();raise HTTPException(409,'Concurrent modification; reload and retry')
        return result

def router(owner):
    api=APIRouter()
    @api.get('/api/ai/status')
    def status(auth=Depends(owner)):
        return {'mode':'private-server','connector':'MCP SDK HTTP endpoint /api/mcp/','client_verified':False,'scopes':['charts:read','drawings:write','notes:write','watchlist:write'],'tools':list(TOOLS),'live_data':False}
    @api.post('/api/ai/tokens')
    def issue(body:TokenRequest,auth=Depends(owner)):
        raw=secrets.token_urlsafe(48);now=int(time.time())
        doc={'id':str(uuid.uuid4()),'label':body.label,'scopes':sorted(set(body.scopes)),'created_at':now,'expires_at':now+body.expires_in_hours*3600,'revoked':False}
        with Session() as db:
            active=[json.loads(r.value) for r in db.scalars(select(Record).where(Record.key.like('ai-token:%')))]
            if sum(not r['revoked'] and r['expires_at']>now for r in active)>=50:raise HTTPException(409,'Revoke an active token before issuing more (maximum 50)')
            db.add(Record(key=token_key(raw),value=json.dumps(doc)));event(db,'owner','ai.token.issue',doc);db.commit()
        return {'token':raw,**doc}
    @api.get('/api/ai/tokens')
    def tokens(auth=Depends(owner)):
        with Session() as db:return [json.loads(r.value) for r in db.scalars(select(Record).where(Record.key.like('ai-token:%')))]
    @api.delete('/api/ai/tokens/{token_id}')
    def revoke(token_id:str,auth=Depends(owner)):
        with Session() as db:
            for rec in db.scalars(select(Record).where(Record.key.like('ai-token:%')).with_for_update()):
                doc=json.loads(rec.value)
                if doc['id']==token_id:
                    doc['revoked']=True;rec.value=json.dumps(doc);event(db,'owner','ai.token.revoke',{'id':token_id});db.commit();return {'revoked':True}
        raise HTTPException(404,'Token not found')
    @api.get('/api/ai/tools')
    def tools(request:Request):
        transport_auth(request.headers)
        return [{'name':n,'description':d,'scope':s,'inputSchema':m.model_json_schema()} for n,(m,s,d) in TOOLS.items()]
    @api.post('/api/ai/tools/{name}')
    def call(name:str,body:dict,request:Request):
        transport_auth(request.headers)
        from pydantic import ValidationError
        try:return execute(name,body,request.headers)
        except ValidationError:raise HTTPException(422,'Invalid AI tool arguments')
    @api.get('/api/ai/notes')
    def notes(auth=Depends(owner)):
        with Session() as db:return [json.loads(r.value) for r in db.scalars(select(Record).where(Record.key.like('ai-note:%')).limit(200))]
    return api
