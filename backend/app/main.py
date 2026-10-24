import hashlib
import json
import os
import secrets
import time
import threading
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from typing import Literal
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError, VerificationError
from fastapi import FastAPI, HTTPException, Request, Response, Depends, UploadFile, File, Form
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, delete
from sqlalchemy.exc import IntegrityError
from .db import Base, engine, Session, Record, Candle, Audit
from .market import parse_csv, aggregate, TIMEFRAMES
from .registry import INSTRUMENTS
from .deployment import cloud_profile

ph = PasswordHasher()
attempts = defaultdict(deque)
login_memory_lock = threading.Lock()
PUBLIC_ORIGIN = os.getenv("PUBLIC_ORIGIN", "http://localhost:3000")
SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"

@asynccontextmanager
async def lifespan(app):
    # Schema is installed by Alembic in production, create_all is for explicit local tests only.
    if os.getenv("AUTO_CREATE_SCHEMA") == "true":
        Base.metadata.create_all(engine)
    from .mcp_server import mcp_app
    mcp=mcp_app.configure()
    async with mcp.session_manager.run():
        yield

app = FastAPI(title="Trading Strategy Lab", version="0.11.0", lifespan=lifespan)

@app.middleware("http")
async def guard(request, call_next):
    if request.method not in ("GET","HEAD","OPTIONS") and request.headers.get("origin") not in (None, PUBLIC_ORIGIN):
        return Response("Origin denied", status_code=403)
    if request.headers.get("content-length", "0").isdigit() and int(request.headers.get("content-length", "0")) > 16_000_000:
        return Response("Request too large", status_code=413)
    if request.method=='POST' and request.url.path.startswith(('/api/ai/','/api/mcp')):
        chunks=[];size=0
        async for chunk in request.stream():
            size+=len(chunk)
            if size>1_000_000:return Response("AI request exceeds 1 MB",status_code=413)
            chunks.append(chunk)
        # Starlette's cached request body is replayed to the downstream ASGI app.
        request._body=b''.join(chunks)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response

def audit(db, action, detail):
    db.add(Audit(time=int(time.time()),actor="owner",action=action,detail=json.dumps(detail)))

def owner(request: Request):
    token = request.cookies.get("tsl_session", "")
    key = "session:" + hashlib.sha256(token.encode()).hexdigest()
    with Session() as db:
        rec = db.get(Record, key)
        if not token or not rec or json.loads(rec.value)["expires"] < time.time():
            raise HTTPException(401, "Authentication required")
    return key

class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Login(Strict):
    password: str = Field(min_length=1,max_length=256)

@app.get("/health")
@app.get("/api/health")
def health():
    with Session() as db:
        db.execute(select(Record).limit(1))
    return {"status":"ok","mode":"research-only","profile":"free-cloud" if cloud_profile() else "standard"}

@app.post("/api/login")
def login(body: Login, request: Request, response: Response):
    ip = request.client.host if request.client else "local"
    q = attempts[ip]
    now = time.time()
    while q and q[0] < now - 900:
        q.popleft()
    if len(q) >= 5:
        raise HTTPException(429,"Too many attempts; wait 15 minutes")
    q.append(now)
    hashed = os.getenv("OWNER_PASSWORD_HASH", "")
    if not hashed:
        raise HTTPException(503,"Owner password is not configured")
    locked = cloud_profile()
    if locked and not login_memory_lock.acquire(blocking=False):
        raise HTTPException(429, "Another password check is running; retry shortly")
    try:
        try:
            ph.verify(hashed, body.password)
        except VerifyMismatchError:
            raise HTTPException(401,"Invalid credentials")
        except (InvalidHashError, VerificationError):
            raise HTTPException(503,"Website login configuration is invalid; the owner must replace OWNER_PASSWORD_HASH") from None
    finally:
        if locked:
            login_memory_lock.release()
    token = secrets.token_urlsafe(48)
    with Session() as db:
        db.add(Record(key="session:"+hashlib.sha256(token.encode()).hexdigest(),value=json.dumps({"expires":now+28800})))
        audit(db,"auth.login",{})
        db.commit()
    response.set_cookie("tsl_session",token,httponly=True,secure=SECURE,samesite="strict",max_age=28800)
    return {"authenticated":True}

@app.get("/api/me")
def me(auth=Depends(owner)):
    return {"user":"owner"}

@app.post("/api/logout")
def logout(response: Response, auth=Depends(owner)):
    with Session() as db:
        db.execute(delete(Record).where(Record.key==auth)); db.commit()
    response.delete_cookie("tsl_session")
    return {"authenticated":False}

@app.get("/api/instruments")
def instruments(auth=Depends(owner)):
    return INSTRUMENTS

def instrument_check(instrument):
    if instrument not in [r["id"] for r in INSTRUMENTS if not r.get("disabled")]:
        raise HTTPException(422,"Unknown or disabled instrument; no silent substitution")

@app.post("/api/import")
async def upload(instrument: str = Form(...), source: str = Form(...,min_length=1,max_length=160),
                 volume_type: Literal["none","tick","exchange"] = Form("none"),
                 rights_confirmed: bool = Form(...), file: UploadFile=File(...), auth=Depends(owner)):
    instrument_check(instrument)
    if not instrument.endswith("-IMPORT"): raise HTTPException(422,"Use the provider import route for provider series")
    if not rights_confirmed:
        raise HTTPException(422,"Confirm authorization to use this dataset")
    max_bytes = 2_000_000 if cloud_profile() else 12_000_000
    raw = await file.read(max_bytes + 1)
    if len(raw)>max_bytes:
        raise HTTPException(413,f"CSV exceeds {max_bytes // 1_000_000} MB for this deployment")
    try:
        rows = parse_csv(raw.decode("utf-8-sig"), max_rows=5000 if cloud_profile() else 100000)
    except (ValueError, UnicodeError) as e:
        raise HTTPException(422,str(e))
    if volume_type == "none" and any(r["volume"] is not None for r in rows):
        raise HTTPException(422,"Declare tick or exchange volume when importing volume")
    now = int(time.time())
    digest = hashlib.sha256(raw).hexdigest()
    with Session() as db:
        # A dataset is replaced atomically: providers cannot be silently mixed.
        db.execute(delete(Candle).where(Candle.instrument==instrument))
        db.add_all([Candle(instrument=instrument,source=source,retrieved_at=now,**r) for r in rows])
        metadata={"source":source,"retrieved_at":now,"sha256":digest,"volume_type":volume_type,
                  "rows":len(rows),"start":rows[0]["time"],"end":rows[-1]["time"],
                  "gaps":sum(b["time"]-a["time"]>60 for a,b in zip(rows,rows[1:])),"rights_confirmed":True}
        db.merge(Record(key="dataset:"+instrument,value=json.dumps(metadata)))
        audit(db,"data.import",dict(metadata,instrument=instrument)); db.commit()
    return metadata

@app.get("/api/candles/{instrument}")
def candles(instrument: str, timeframe: str="5m", before: int|None=None, auth=Depends(owner)):
    instrument_check(instrument)
    if timeframe not in TIMEFRAMES:
        raise HTTPException(422,"Unsupported timeframe")
    with Session() as db:
        meta = db.get(Record,"dataset:"+instrument)
        if not meta:
            return {"candles":[],"quality":{"state":"NO DATA"},"dataset":None}
        stmt = select(Candle).where(Candle.instrument==instrument)
        if before is not None:
            stmt = stmt.where(Candle.time<before)
        # Aggregate full imported dataset before paging so a bucket is never cut at a raw row limit.
        raw = db.scalars(stmt.order_by(Candle.time)).all()
        rows = aggregate([{k:getattr(c,k) for k in ("time","open","high","low","close","volume")} for c in raw],timeframe)
        metadata = json.loads(meta.value)
    stale = time.time()-metadata["end"]>180
    return {"candles":rows[-2000:],"has_more":len(rows)>2000,"dataset":metadata,
            "quality":{"state":"WAIT" if stale or metadata["gaps"] else "HISTORICAL ONLY",
                       "stale":stale,"live":False,"gaps":metadata["gaps"],
                       "message":"Imported research bars; never executable live quotes. Gaps may include market closures. Aggregates contain observed bars only."}}

class Point(Strict):
    time: int = Field(ge=0)
    price: float

class Drawing(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,80}$")
    kind: Literal["horizontal","trendline","rectangle","note"]
    points: list[Point] = Field(min_length=1,max_length=2)
    text: str = Field(default="",max_length=500)
    version: int = Field(ge=0)
    @model_validator(mode="after")
    def coordinates(self):
        if len(self.points) != (2 if self.kind in ("trendline","rectangle") else 1):
            raise ValueError("Incorrect number of coordinates")
        return self

@app.get("/api/drawings/{instrument}")
def drawings(instrument: str, auth=Depends(owner)):
    instrument_check(instrument)
    with Session() as db:
        items=db.scalars(select(Record).where(Record.key.like("drawing:"+instrument+":%"))).all()
        return [json.loads(r.value) for r in items]

@app.put("/api/drawings/{instrument}")
def save_drawing(instrument: str, body: Drawing, auth=Depends(owner)):
    instrument_check(instrument)
    key="drawing:"+instrument+":"+body.id
    with Session() as db:
        old=db.scalar(select(Record).where(Record.key==key).with_for_update())
        prev=json.loads(old.value) if old else None
        if body.version != (prev["version"] if prev else 0):
            raise HTTPException(409,"Drawing changed; reload before saving")
        doc=body.model_dump() | {"version":body.version+1,"owner":"owner","provenance":prev.get("provenance","manual") if prev else "manual","created_by":prev.get("created_by","owner") if prev else "owner","updated_by":"owner","updated_at":int(time.time())}
        db.merge(Record(key=key,value=json.dumps(doc)))
        audit(db,"drawing.save",{"instrument":instrument,"before":prev,"after":doc})
        try:db.commit()
        except IntegrityError:
            db.rollback();raise HTTPException(409,"Concurrent drawing creation; reload before saving")
    return doc

@app.delete("/api/drawings/{instrument}/{drawing_id}")
def delete_drawing(instrument: str, drawing_id: str, version: int, auth=Depends(owner)):
    instrument_check(instrument)
    with Session() as db:
        old=db.scalar(select(Record).where(Record.key=="drawing:"+instrument+":"+drawing_id).with_for_update())
        if not old: raise HTTPException(404,"Drawing not found")
        doc=json.loads(old.value)
        if doc["version"]!=version: raise HTTPException(409,"Version conflict")
        db.delete(old); audit(db,"drawing.delete",{"instrument":instrument,"before":doc}); db.commit()
    return {"deleted":True}

@app.get("/api/watchlist")
def watchlist(auth=Depends(owner)):
    with Session() as db:
        r=db.get(Record,"watchlist")
        return json.loads(r.value) if r else ["XAUUSD-IMPORT","NDX-IMPORT"]

class Watchlist(Strict):
    instruments:list[str]=Field(max_length=50)

@app.put("/api/watchlist")
def save_watchlist(body:Watchlist,auth=Depends(owner)):
    for i in body.instruments: instrument_check(i)
    with Session() as db:
        version=db.get(Record,"watchlist-version",with_for_update=True)
        db.merge(Record(key="watchlist-version",value=json.dumps((json.loads(version.value) if version else 0)+1)))
        db.merge(Record(key="watchlist",value=json.dumps(list(dict.fromkeys(body.instruments)))))
        audit(db,"watchlist.update",body.model_dump());db.commit()
    return body.instruments

@app.get("/api/audit")
def audit_history(auth=Depends(owner)):
    with Session() as db:
        return [{"id":r.id,"time":r.time,"actor":r.actor,"action":r.action,"detail":json.loads(r.detail)}
                for r in db.scalars(select(Audit).order_by(Audit.id.desc()).limit(200))]


class ResearchRecord(Strict):
    id: str = Field(pattern=r"^[a-zA-Z0-9-]{1,128}$")
    title: str = Field(max_length=200)
    created_at: int = Field(ge=0)
    payload: dict

@app.get("/api/research/{kind}")
def research_records(kind: Literal["backtests","journal","alert-rules","alert-events"], auth=Depends(owner)):
    with Session() as db:
        rows=db.scalars(select(Record).where(Record.key.like("research:"+kind+":%"))).all()
        return sorted([json.loads(r.value) for r in rows],key=lambda r:r["created_at"],reverse=True)

@app.put("/api/research/{kind}")
def save_research_record(kind: Literal["backtests","journal","alert-rules","alert-events"], body: ResearchRecord, auth=Depends(owner)):
    encoded=body.model_dump_json()
    if len(encoded)>6_000_000: raise HTTPException(413,"Research record exceeds 6 MB")
    with Session() as db:
        key="research:"+kind+":"+body.id
        if kind=="alert-events":
            prior=db.get(Record,key)
            if prior: return json.loads(prior.value)
        db.merge(Record(key=key,value=encoded))
        audit(db,"research."+kind+".save",{"id":body.id,"title":body.title})
        db.commit()
    return body.model_dump()


from .provider_api import attach
app.include_router(attach(owner,audit))

from .ai_access import router as ai_router
from .mcp_server import mcp_app
app.include_router(ai_router(owner))
app.mount('/api/mcp',mcp_app)
