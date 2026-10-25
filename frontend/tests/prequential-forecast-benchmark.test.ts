import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evaluatePrequentialForecastBenchmark as evaluate} from '../lib/prequential-forecast-benchmark.ts';
import type {ForecastRecord,FeedIdentity} from '../lib/forward-forecast-ledger.ts';
const identity:FeedIdentity={instrument:'FIXTURE-XAUUSD',provider:'fixture',venue:'fixture',sourceId:'A',priceSide:'bid',seconds:60};
const origin=1800000000;
function series(n=50,horizon:1|3|12=1,modelVersion='v1',p=0.6):ForecastRecord[]{
 const first=Math.ceil(origin/(horizon*60))*horizon*60;
 return Array.from({length:n},(_,i)=>{
  const baseStart=first+i*horizon*60;
  const targetStart=baseStart+horizon*60;
  return {id:`${modelVersion}-${horizon}-${i}`,modelVersion,horizon,probability:p,
   ...identity,baseStart,baseClose:100,issuedAt:baseStart+61,targetStart,
   status:'SETTLED' as const,resolvedAt:targetStart+61,outcomeUp:i%2===0,reason:null};
 });
}
const clock=(rows:ForecastRecord[])=>rows.at(-1)!.targetStart+100;
test('prequential score is source-labelled and no execution or performance claims',()=>{
 const rows=series();const x=evaluate(rows,identity,'v1',1,clock(rows));
 assert.equal(x.status,'REPORT');assert.equal(x.scored,20);assert.equal(x.live,false);
 assert.equal(x.execution,'NONE');assert.equal(x.persisted,false);
 assert.ok(x.adaptiveReferenceBrier!>0);assert.ok(Number.isFinite(x.brierSkillVsAdaptive));
 assert.equal(x.latestTargetClose,rows.at(-1)!.targetStart+60);
});
test('reference is adaptive, not a fixed 50 percent comparator',()=>{
 const rows=series(50,1,'v1',0.7).map((r,i)=>({...r,outcomeUp:i<30||i%2===0}));
 const x=evaluate(rows,identity,'v1',1,clock(rows));
 assert.equal(x.status,'REPORT');assert.notEqual(x.adaptiveReferenceBrier,0.25);
});
test('probabilities and horizons are isolated from other versions',()=>{
 const rows=series();const mixed=[...rows,...series(50,3,'v2',0.9)];
 assert.deepEqual(evaluate(mixed,identity,'v1',1,clock(mixed)),evaluate(rows,identity,'v1',1,clock(rows)));
});
test('all three horizon phases can be scored without overlapping outcome windows',()=>{
 for(const h of [1,3,12] as const){const rows=series(45,h);const x=evaluate(rows,identity,'v1',h,clock(rows));
  assert.equal(x.status,'REPORT');assert.equal(x.scored,20);}
});
test('incomplete training or evaluation returns insufficient rather than cherry-picking',()=>{
 const rows=series(39);assert.equal(evaluate(rows,identity,'v1',1,clock(rows)).status,'INSUFFICIENT');
 const longer=series(45);longer[25]={...longer[25],status:'VOID_GAP',outcomeUp:null};
 assert.equal(evaluate(longer,identity,'v1',1,clock(longer)).status,'INSUFFICIENT');
});
test('missing interval in scored window fails closed',()=>{
 const rows=series();rows.splice(32,1);
 assert.match(evaluate(rows,identity,'v1',1,clock(rows)).reason!,/Missing aligned/);
});
test('late resolution cannot leak future outcomes into adaptive reference',()=>{
 const rows=series();rows[20]={...rows[20],resolvedAt:rows[35].issuedAt};
 assert.match(evaluate(rows,identity,'v1',1,clock(rows)).reason!,/not known/);
});
test('unresolved latest tail before close is excluded; overdue pending blocks',()=>{
 const rows=series();const last=rows.at(-1)!;
 const pending={...last,id:'next',baseStart:last.baseStart+60,targetStart:last.targetStart+60,
  issuedAt:last.issuedAt+60,status:'PENDING' as const,resolvedAt:null,outcomeUp:null};
 const x=evaluate([...rows,pending],identity,'v1',1,pending.issuedAt);
 assert.equal(x.status,'REPORT');assert.equal(x.scored,20);
 assert.match(evaluate([...rows,pending],identity,'v1',1,pending.targetStart+60).reason!,/Overdue/);
});
test('mixed feed identity, duplicates and malformed price fail closed',()=>{
 const rows=series();
 assert.throws(()=>evaluate([...rows,{...rows[0],sourceId:'B'}],identity,'v1',1,clock(rows)));
 assert.throws(()=>evaluate([...rows,rows[0]],identity,'v1',1,clock(rows)));
 assert.throws(()=>evaluate(rows.map((r,i)=>i===3?{...r,probability:1}:r),identity,'v1',1,clock(rows)));
});
test('future issuance and premature resolution are rejected',()=>{
 const rows=series();
 assert.throws(()=>evaluate(rows,identity,'v1',1,rows[10].issuedAt));
 assert.throws(()=>evaluate(rows.map((r,i)=>i===5?{...r,resolvedAt:r.targetStart}:r),identity,'v1',1,clock(rows)));
});
test('invalid configuration fails closed',()=>{
 const rows=series();
 assert.throws(()=>evaluate(rows,identity,'v1',1,clock(rows),19));
 assert.throws(()=>evaluate(rows,identity,'v1',1,clock(rows),20,501));
 assert.throws(()=>evaluate(rows,identity,'v1',1,-1));
});
test('deterministic evaluation and no mutation of inputs',()=>{
 const rows=series();const before=JSON.stringify(rows);
 assert.deepEqual(evaluate(rows,identity,'v1',1,clock(rows)),evaluate(rows,identity,'v1',1,clock(rows)));
 assert.equal(JSON.stringify(rows),before);
});
test('a systematically overconfident model is worse than adaptive benchmark',()=>{
 const rows=series(60,1,'v1',0.99);const x=evaluate(rows,identity,'v1',1,clock(rows));
 assert.equal(x.status,'REPORT');assert.ok(x.brierSkillVsAdaptive!<0);
 assert.ok(x.maxConsecutiveUnderperformance!>=1);
});
