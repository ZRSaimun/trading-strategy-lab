import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ForecastReviewOutbox,reviewForwardCalibration} from '../lib/forecast-review-outbox.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';
const identity:FeedIdentity={instrument:'XAUUSD-TEST',provider:'fixture',venue:'test',sourceId:'feed-A',priceSide:'bid',seconds:60};
const start=1800000000;
const at=(data:ForecastRecord[])=>Math.max(...data.map(r=>r.resolvedAt??r.issuedAt))+100;
const review=(data:ForecastRecord[],modelVersion='v1',horizon:1|3|12=1)=>
 reviewForwardCalibration(data,identity,modelVersion,horizon,at(data));
function records(h:1|3|12=1,count=40,changeAt=20):ForecastRecord[]{
 return Array.from({length:count},(_,i)=>{
  const baseStart=start+i*h*60;
  return {id:'f'+i,modelVersion:'v1',horizon:h,probability:i<changeAt?.9:.1,
   ...identity,baseStart,baseClose:100,issuedAt:baseStart+60,
   targetStart:baseStart+h*60,status:'SETTLED',resolvedAt:baseStart+(h+1)*60,
   outcomeUp:true,reason:null};
 });
}
test('detects degraded Brier scores and emits exactly one offline review candidate',()=>{
 const data=records();const outbox=new ForecastReviewOutbox(identity,'v1',1);
 const result=review(data,'v1',1);
 assert.equal(result.status,'REVIEW');assert.ok(result.deltaBrier!>0.7);
 const [event]=outbox.evaluate(data,at(data));
 assert.equal(event.mode,'UNVERIFIED_LOCAL_RESEARCH');assert.equal(event.live,false);
 assert.equal(event.delivery,'NOT_CONNECTED');assert.equal(event.execution,'NONE');
 assert.deepEqual(outbox.evaluate(data,at(data)),[]);
});
test('insufficient and pending or void outcomes fail closed',()=>{
 assert.equal(review(records(1,39),'v1',1).status,'INSUFFICIENT');
 const data=records();data[25].status='VOID_GAP';data[25].outcomeUp=null;
 assert.equal(review(data,'v1',1).status,'INSUFFICIENT');
 assert.deepEqual(new ForecastReviewOutbox(identity,'v1',1).evaluate(data,at(data)),[]);
});
test('non-overlapping horizon-3 phase with continuous outcomes is scored',()=>{
 const data=records(3);
 assert.equal(review(data,'v1',3).status,'REVIEW');
 data[20].baseStart+=60;data[20].issuedAt+=60;data[20].targetStart+=60;data[20].resolvedAt=data[20].resolvedAt!+60;
 assert.equal(review(data,'v1',3).status,'INSUFFICIENT');
});
test('source, version, horizon and duplicate candle isolation',()=>{
 const data=records();
 assert.throws(()=>review([...data,{...data[0],sourceId:'other'}],'v1',1),/source/);
 assert.throws(()=>review([...data,{...data[0],id:'duplicate'}],'v1',1),/Duplicate/);
 assert.equal(review(data,'v2',1).status,'INSUFFICIENT');
 assert.equal(review(data,'v1',12).status,'INSUFFICIENT');
});
test('does not produce a review when the recent window improves',()=>{
 const data=records(1,40,20).map((r,i)=>({...r,probability:i<20?.1:.9}));
 assert.equal(review(data,'v1',1).status,'NO_FLAG');
 assert.deepEqual(new ForecastReviewOutbox(identity,'v1',1).evaluate(data,at(data)),[]);
});
test('same event is idempotent; later newly settled review can be emitted',()=>{
 const outbox=new ForecastReviewOutbox(identity,'v1',1);
 const data=records();assert.equal(outbox.evaluate(data,at(data)).length,1);
 const extra={...data[39],id:'next',baseStart:data[39].baseStart+60,
  targetStart:data[39].targetStart+60,issuedAt:data[39].issuedAt+60,resolvedAt:data[39].resolvedAt!+60};
 assert.equal(outbox.evaluate([...data,extra],at([...data,extra])).length,1);
 assert.equal(outbox.evaluate([...data,extra],at([...data,extra])).length,0);
});
test('rejects invalid settlement time and non-finite probability',()=>{
 const data=records();data[5].resolvedAt=data[5].targetStart;
 assert.throws(()=>review(data,'v1',1),/Malformed/);
 data[5].resolvedAt=data[5].targetStart+60;data[5].probability=NaN;
 assert.throws(()=>review(data,'v1',1),/Malformed/);
});

test('rejects forecasts issued after next candle closed',()=>{
 const data=records();data[1].issuedAt=data[1].baseStart+120;
 assert.throws(()=>review(data,'v1',1),/Malformed/);
});

test('explicit asOf rejects future settlement and future-issued predictions',()=>{
 const data=records();
 const asOf=data.at(-1)!.resolvedAt!;
 assert.equal(reviewForwardCalibration(data,identity,'v1',1,asOf).status,'REVIEW');
 const future=records();future[39].resolvedAt=asOf+1;
 assert.throws(()=>reviewForwardCalibration(future,identity,'v1',1,asOf),/future-dated/);
 const late=records();late[39].issuedAt=asOf+1;
 assert.throws(()=>reviewForwardCalibration(late,identity,'v1',1,asOf),/future-dated/);
});
test('malformed pending/void records and nonpositive base prices fail closed',()=>{
 const pending=records();pending[2].status='PENDING';pending[2].outcomeUp=null;
 assert.throws(()=>review(pending),/Malformed/);
 const voided=records();voided[3].status='VOID_GAP';voided[3].outcomeUp=null;
 voided[3].resolvedAt=null;
 assert.throws(()=>review(voided),/Malformed/);
 const price=records();price[5].baseClose=0;
 assert.throws(()=>review(price),/Malformed/);
});
test('overdue pending forecasts block review rather than emitting stale candidates',()=>{
 const data=records();data[39].status='PENDING';data[39].outcomeUp=null;data[39].resolvedAt=null;
 const asOf=records()[39].resolvedAt!;
 const result=reviewForwardCalibration(data,identity,'v1',1,asOf);
 assert.equal(result.status,'INSUFFICIENT');
 assert.match(result.reasons[0],/Unresolved/);
 assert.deepEqual(new ForecastReviewOutbox(identity,'v1',1).evaluate(data,asOf),[]);
});
