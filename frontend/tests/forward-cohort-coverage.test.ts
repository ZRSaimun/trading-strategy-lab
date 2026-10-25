import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditForwardCohortCoverage} from '../lib/forward-cohort-coverage.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';

const feed:FeedIdentity={instrument:'XAUUSD-TEST',provider:'fixture',venue:'test',sourceId:'A',priceSide:'bid',seconds:60};
const origin=1800000000;
function fixture(h:1|3|12=1,n=5):ForecastRecord[]{
 return Array.from({length:n},(_,i)=>{
  const baseStart=origin+i*h*60;
  return {...feed,id:`f${i}`,modelVersion:'v1',horizon:h,probability:.6,
   baseStart,baseClose:100,issuedAt:baseStart+60,
   targetStart:baseStart+h*60,status:'SETTLED',
   resolvedAt:baseStart+(h+1)*60,outcomeUp:i%2===0,reason:null};
 });
}
function audit(rows:ForecastRecord[],h:1|3|12=1,asOf?:number,lag=120){
 const start=origin,end=origin+4*h*60;
 return auditForwardCohortCoverage(rows,feed,'v1',h,start,end,
   asOf??end+(h+1)*60,lag);
}
test('complete fixed-phase cohort is descriptive, never live or executable',()=>{
 const r=audit(fixture());
 assert.equal(r.status,'COMPLETE_DESCRIPTIVE');
 assert.equal(r.expectedSlots,5);assert.equal(r.maturedSlots,5);
 assert.equal(r.matureTimelyCoverage,1);assert.equal(r.live,false);
 assert.equal(r.authenticated,false);assert.equal(r.execution,'NONE');
});
test('one absent matured issue reduces coverage instead of hiding attrition',()=>{
 const rows=fixture();rows.splice(2,1);
 const r=audit(rows);
 assert.equal(r.status,'INCOMPLETE');assert.equal(r.missingMatured,1);
 assert.equal(r.matureTimelyCoverage,.8);
});
test('gap-void is not mis-scored as a directional loss',()=>{
 const rows=fixture();rows[2]={...rows[2],status:'VOID_GAP',outcomeUp:null,reason:'gap'};
 const r=audit(rows);assert.equal(r.voidGap,1);
 assert.equal(r.timelySettled,4);assert.equal(r.matureTimelyCoverage,.8);
});
test('matured pending is overdue and immature pending is not',()=>{
 const rows=fixture();rows[4]={...rows[4],status:'PENDING',resolvedAt:null,outcomeUp:null};
 const mature=audit(rows);assert.equal(mature.overduePending,1);
 const early=audit(rows,1,rows[3].resolvedAt!);
 assert.equal(early.immaturePending,1);assert.equal(early.overduePending,0);
 assert.equal(early.maturedSlots,4);
});
test('not-yet-mature single forecast is explicit',()=>{
 const rows=fixture(12,1);rows[0]={...rows[0],status:'PENDING',resolvedAt:null,outcomeUp:null};
 const r=auditForwardCohortCoverage(rows,feed,'v1',12,origin,origin,origin+60);
 assert.equal(r.status,'NOT_YET_MATURE');assert.equal(r.matureTimelyCoverage,null);
});
test('late settlement is separate from observed outcome and penalizes coverage',()=>{
 const rows=fixture();rows[2]={...rows[2],resolvedAt:rows[2].resolvedAt!+121};
 const r=audit(rows,1,origin+900);assert.equal(r.lateSettled,1);assert.equal(r.matureTimelyCoverage,.8);
 assert.equal(audit(rows,1,origin+900,121).status,'COMPLETE_DESCRIPTIVE');
});
test('1, 3 and 12 candle horizons use non-overlapping fixed UTC phases',()=>{
 for(const h of [1,3,12] as const){
  assert.equal(audit(fixture(h),h).status,'COMPLETE_DESCRIPTIVE');
 }
});
test('rejects duplicate slots, even with different record ids',()=>{
 const rows=fixture();assert.throws(()=>audit([...rows,{...rows[0],id:'duplicate'}]),/Duplicate/);
});
test('rejects mixed feeds, out-of-cohort and misaligned base starts',()=>{
 const rows=fixture();assert.throws(()=>audit([...rows,{...rows[0],sourceId:'B'}]),/source/);
 const wrong=fixture();wrong[0].baseStart+=60;
 assert.throws(()=>audit(wrong),/Duplicate|Malformed/);
 const beyond=fixture();beyond[0].baseStart-=60;
 assert.throws(()=>audit(beyond),/Malformed/);
});
test('rejects retroactive issuance, premature settlement and future receipt',()=>{
 const lateIssue=fixture();lateIssue[0].issuedAt=lateIssue[0].targetStart+60;
 assert.throws(()=>audit(lateIssue),/Malformed/);
 const earlySettle=fixture();earlySettle[0].resolvedAt=earlySettle[0].targetStart;
 assert.throws(()=>audit(earlySettle),/Malformed/);
 const future=fixture();future[4].resolvedAt!+=1000;
 assert.throws(()=>audit(future),/Malformed/);
});
test('rejects malformed state and invalid numeric observations',()=>{
 const rows=fixture();rows[0].probability=NaN;
 assert.throws(()=>audit(rows),/Malformed/);
 const rows2=fixture();rows2[0].status='PENDING';
 assert.throws(()=>audit(rows2),/Malformed/);
 const rows3=fixture();rows3[0].status='VOID_GAP';rows3[0].outcomeUp=null;
 assert.throws(()=>audit(rows3),/Malformed/);
});
test('rejects unbounded, non-phase, reversed and future cohort windows',()=>{
 const rows=fixture();
 assert.throws(()=>auditForwardCohortCoverage(rows,feed,'v1',1,origin,origin+5001*60,origin+6000*60),/capacity/);
 assert.throws(()=>auditForwardCohortCoverage(rows,feed,'v1',3,origin,origin+60,origin+5000),/bounds/);
 assert.throws(()=>auditForwardCohortCoverage(rows,feed,'v1',1,origin+60,origin,origin+5000),/bounds/);
 assert.throws(()=>auditForwardCohortCoverage(rows,feed,'v1',1,origin,origin+240,origin),/bounds/);
});
test('different model/horizon records are not pooled',()=>{
 const rows=fixture();const other={...rows[0],modelVersion:'v2',id:'other'};
 assert.equal(audit([...rows,other]).status,'COMPLETE_DESCRIPTIVE');
 const otherH={...rows[0],horizon:3 as const,targetStart:rows[0].baseStart+180,id:'otherH'};
 assert.equal(audit([...rows,otherH]).status,'COMPLETE_DESCRIPTIVE');
});
test('does not mutate input rows or leak a mutable input reference',()=>{
 const rows=fixture();const before=JSON.stringify(rows);const r=audit(rows);
 r.reasons.push('changed');assert.equal(JSON.stringify(rows),before);
 assert.equal(audit(rows).reasons.length,0);
});
