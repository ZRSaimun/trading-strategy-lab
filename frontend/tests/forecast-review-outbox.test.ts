import {test} from 'node:test';
import assert from 'node:assert/strict';
import {ForecastReviewOutbox,reviewForwardCalibration} from '../lib/forecast-review-outbox.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';
const identity:FeedIdentity={instrument:'XAUUSD-TEST',provider:'fixture',venue:'test',sourceId:'feed-A',priceSide:'bid',seconds:60};
const start=1800000000;
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
 const result=reviewForwardCalibration(data,identity,'v1',1);
 assert.equal(result.status,'REVIEW');assert.ok(result.deltaBrier!>0.7);
 const [event]=outbox.evaluate(data);
 assert.equal(event.mode,'UNVERIFIED_LOCAL_RESEARCH');assert.equal(event.live,false);
 assert.equal(event.delivery,'NOT_CONNECTED');assert.equal(event.execution,'NONE');
 assert.deepEqual(outbox.evaluate(data),[]);
});
test('insufficient and pending or void outcomes fail closed',()=>{
 assert.equal(reviewForwardCalibration(records(1,39),identity,'v1',1).status,'INSUFFICIENT');
 const data=records();data[25].status='VOID_GAP';data[25].outcomeUp=null;
 assert.equal(reviewForwardCalibration(data,identity,'v1',1).status,'INSUFFICIENT');
 assert.deepEqual(new ForecastReviewOutbox(identity,'v1',1).evaluate(data),[]);
});
test('non-overlapping horizon-3 phase with continuous outcomes is scored',()=>{
 const data=records(3);
 assert.equal(reviewForwardCalibration(data,identity,'v1',3).status,'REVIEW');
 data[20].baseStart+=60;data[20].targetStart+=60;data[20].resolvedAt=data[20].resolvedAt!+60;
 assert.equal(reviewForwardCalibration(data,identity,'v1',3).status,'INSUFFICIENT');
});
test('source, version, horizon and duplicate candle isolation',()=>{
 const data=records();
 assert.throws(()=>reviewForwardCalibration([...data,{...data[0],sourceId:'other'}],identity,'v1',1),/source/);
 assert.throws(()=>reviewForwardCalibration([...data,{...data[0],id:'duplicate'}],identity,'v1',1),/Duplicate/);
 assert.equal(reviewForwardCalibration(data,identity,'v2',1).status,'INSUFFICIENT');
 assert.equal(reviewForwardCalibration(data,identity,'v1',12).status,'INSUFFICIENT');
});
test('does not produce a review when the recent window improves',()=>{
 const data=records(1,40,20).map((r,i)=>({...r,probability:i<20?.1:.9}));
 assert.equal(reviewForwardCalibration(data,identity,'v1',1).status,'NO_FLAG');
 assert.deepEqual(new ForecastReviewOutbox(identity,'v1',1).evaluate(data),[]);
});
test('same event is idempotent; later newly settled review can be emitted',()=>{
 const outbox=new ForecastReviewOutbox(identity,'v1',1);
 const data=records();assert.equal(outbox.evaluate(data).length,1);
 const extra={...data[39],id:'next',baseStart:data[39].baseStart+60,
  targetStart:data[39].targetStart+60,issuedAt:data[39].issuedAt+60,resolvedAt:data[39].resolvedAt!+60};
 assert.equal(outbox.evaluate([...data,extra]).length,1);
 assert.equal(outbox.evaluate([...data,extra]).length,0);
});
test('rejects invalid settlement time and non-finite probability',()=>{
 const data=records();data[5].resolvedAt=data[5].targetStart;
 assert.throws(()=>reviewForwardCalibration(data,identity,'v1',1),/Malformed/);
 data[5].resolvedAt=data[5].targetStart+60;data[5].probability=NaN;
 assert.throws(()=>reviewForwardCalibration(data,identity,'v1',1),/Malformed/);
});
