import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ForwardForecastJournal,type ForecastCheckpoint} from '../lib/forward-forecast-journal.ts';
import type {FeedIdentity} from '../lib/forward-forecast-ledger.ts';
const identity:FeedIdentity={instrument:'XAUUSD-OTC',provider:'Synthetic',venue:'TEST',sourceId:'A',priceSide:'bid',seconds:60};
const base=1800000000;
const clock={now:base+60};
const candle=(start:number,close:number)=>({identity,start,close});
const journal=()=>new ForwardForecastJournal(identity,()=>clock.now,30);
const forecast=(id:string,horizon:1|3|12=1)=>({id,modelVersion:'v1',horizon,probability:.7});
function initial():ForwardForecastJournal{
 clock.now=base+60;const j=journal();j.receive(candle(base,100));j.issue(forecast('a'));
 return j;
}

test('checkpoint restores pending forecasts, then settles only on later received candle',()=>{
 const j=initial(),snapshot=j.checkpoint();
 assert.equal(snapshot.evidence,'UNVERIFIED_LOCAL_EVENT_LOG');
 clock.now=base+70;
 const resumed=ForwardForecastJournal.restore(snapshot,()=>clock.now);
 assert.deepEqual(resumed.summary(),j.summary());
 assert.equal(resumed.entries()[0].status,'PENDING');
 clock.now=base+120;resumed.receive(candle(base+60,101));
 assert.equal(resumed.entries()[0].status,'SETTLED');
 assert.equal(resumed.entries()[0].outcomeUp,true);
 assert.ok(Math.abs(resumed.summary().brier!-.09)<1e-12);
 assert.equal(resumed.checkpoint().events.length,3);
});

test('gap voids pending forecasts identically across a restart',()=>{
 const j=initial();j.issue(forecast('b',3));
 clock.now=base+240;
 const resumed=ForwardForecastJournal.restore(j.checkpoint(),()=>clock.now);
 resumed.receive(candle(base+180,120));
 assert.equal(resumed.summary().voidGap,2);
 assert.equal(resumed.summary().settled,0);
});

test('duplicate receive and retry do not add events; conflicting id or model/bar key fails',()=>{
 const j=initial();
 const before=j.checkpoint().events.length;
 j.receive(candle(base,100));j.issue(forecast('a'));
 assert.equal(j.checkpoint().events.length,before);
 assert.throws(()=>j.issue({...forecast('a'),probability:.6}),/Conflicting/);
 assert.throws(()=>j.issue(forecast('b')),/already issued/);
 assert.equal(j.checkpoint().events.length,before);
 clock.now=base+70;
 const resumed=ForwardForecastJournal.restore(j.checkpoint(),()=>clock.now);
 assert.throws(()=>resumed.issue(forecast('b')),/already issued/);
});

test('restored state and checkpoints are detached from external object mutations',()=>{
 const j=initial();const snapshot=j.checkpoint();
 snapshot.events[0].kind==='CANDLE'&&(snapshot.events[0].candle.close=1);
 assert.equal(j.checkpoint().events[0].kind==='CANDLE'&&(j.checkpoint().events[0] as any).candle.close,100);
 const good=j.checkpoint();clock.now=base+70;
 const restored=ForwardForecastJournal.restore(good,()=>clock.now);
 good.identity.sourceId='forged';
 if(good.events[1].kind==='FORECAST')good.events[1].forecast.probability=.1;
 assert.equal(restored.identity.sourceId,'A');
 assert.equal(restored.entries()[0].probability,.7);
});

test('rejects forged timestamps, duplicate sequences, extra fields and wrong source',()=>{
 const j=initial();const snapshot=j.checkpoint();clock.now=base+120;
 const tamper=(mutate:(s:ForecastCheckpoint)=>void)=>{const copy=structuredClone(snapshot);mutate(copy);return copy};
 assert.throws(()=>ForwardForecastJournal.restore(tamper(s=>{s.events[0].receivedAt=base+121}),()=>clock.now),/future-dated/);
 assert.throws(()=>ForwardForecastJournal.restore(tamper(s=>{s.events[1].sequence=1}),()=>clock.now),/reordered/);
 assert.throws(()=>ForwardForecastJournal.restore(tamper(s=>{(s.events[0] as any).extra='x'}),()=>clock.now),/Malformed/);
 assert.throws(()=>ForwardForecastJournal.restore(tamper(s=>{if(s.events[0].kind==='CANDLE')s.events[0].candle.identity.sourceId='B'}),()=>clock.now),/identity mismatch/);
 assert.throws(()=>ForwardForecastJournal.restore(tamper(s=>{s.events[1].receivedAt=base+59}),()=>clock.now),/backward/);
});

test('restart cannot retroactively issue forecast after target closed or stale base',()=>{
 const j=initial();clock.now=base+300;
 const restored=ForwardForecastJournal.restore(j.checkpoint(),()=>clock.now);
 assert.throws(()=>restored.issue(forecast('late',3)),/No recent/);
 assert.equal(restored.checkpoint().events.length,2);
});

test('rejects invalid checkpoint envelope, future clock, malformed event and backward clock',()=>{
 const j=initial(),s=j.checkpoint();clock.now=base+70;
 assert.throws(()=>ForwardForecastJournal.restore({...s,version:2},()=>clock.now),/Invalid/);
 assert.throws(()=>ForwardForecastJournal.restore({...s,evidence:'LIVE_VERIFIED'},()=>clock.now),/Invalid/);
 assert.throws(()=>ForwardForecastJournal.restore({...s,events:[{...s.events[0],kind:'HACK'}]},()=>clock.now),/Malformed/);
 const resumed=ForwardForecastJournal.restore(s,()=>clock.now);
 clock.now=base+59;
 assert.throws(()=>resumed.receive(candle(base+60,102)),/backward/);
 assert.equal(resumed.checkpoint().events.length,2);
});

test('checkpoint replay rejects long-horizon issuance after the next candle closed',()=>{
 clock.now=base+60;
 const j=new ForwardForecastJournal(identity,()=>clock.now,3600);
 j.receive(candle(base,100));j.issue(forecast('long',12));
 const checkpoint=j.checkpoint();clock.now=base+240;
 const forged=structuredClone(checkpoint);
 forged.events[1].receivedAt=base+120;
 assert.throws(()=>ForwardForecastJournal.restore(forged,()=>clock.now),/retroactive/);
 assert.equal(j.checkpoint().events[1].receivedAt,base+60);
});
