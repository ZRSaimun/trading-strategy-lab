import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evaluateForwardReliability} from '../lib/forward-reliability.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';
const feed:FeedIdentity={instrument:'XAUUSD-TEST',provider:'fixture',venue:'test',sourceId:'source-A',priceSide:'bid',seconds:60};
const t0=1800000000;
function rows(h:1|3|12=1,n=100,p=.5):ForecastRecord[]{
 return Array.from({length:n},(_,i)=>{
  const baseStart=t0+i*h*60;
  return {...feed,id:'r'+i,modelVersion:'v1',horizon:h,probability:p,
   baseStart,baseClose:100,issuedAt:baseStart+60,targetStart:baseStart+h*60,
   status:'SETTLED',resolvedAt:baseStart+(h+1)*60,
   outcomeUp:i%2===0,reason:null};
 });
}
const asOf=(r:ForecastRecord[])=>Math.max(...r.map(x=>x.resolvedAt??x.issuedAt))+100;
const run=(r:ForecastRecord[],h:1|3|12=1,n=100)=>evaluateForwardReliability(r,feed,'v1',h,asOf(r),n);

test('well-calibrated synthetic 50% forecasts have zero ECE and Brier skill',()=>{
 const result=run(rows());
 assert.equal(result.status,'REPORT');assert.equal(result.selected,100);
 assert.equal(result.brier,.25);assert.equal(result.brierSkill,0);
 assert.equal(result.expectedCalibrationError,0);
 assert.equal(result.bins[2].count,100);
 assert.ok(result.bins[2].wilson95Lower!<.5);
 assert.ok(result.bins[2].wilson95Upper!>.5);
 assert.equal(result.live,false);
});
test('confident incorrect forecasts report poor calibration, never returns',()=>{
 const result=run(rows(1,100,.9));
 assert.equal(result.status,'REPORT');
 assert.ok(result.brier!>.4);
 assert.ok(result.brierSkill!<0);
 assert.ok(result.expectedCalibrationError!>.39);
 assert.equal(result.bins[4].count,100);
});
test('horizon 12 uses only fixed non-overlapping UTC phase',()=>{
 const data=rows(12);
 assert.equal(run(data,12).status,'REPORT');
 const moved=data.map(x=>({...x}));
 moved[60].baseStart+=60;moved[60].issuedAt+=60;moved[60].targetStart+=60;moved[60].resolvedAt!+=60;
 assert.equal(run(moved,12).status,'INSUFFICIENT');
});
test('pending tail is ignored but an internal void or missing interval fails closed',()=>{
 const data=rows();
 const pending={...data.at(-1)!,id:'tail',baseStart:data.at(-1)!.baseStart+60,
   issuedAt:data.at(-1)!.issuedAt+60,targetStart:data.at(-1)!.targetStart+60,
   status:'PENDING' as const,resolvedAt:null,outcomeUp:null};
 const result=evaluateForwardReliability([...data,pending],feed,'v1',1,data.at(-1)!.resolvedAt!);
 assert.equal(result.status,'REPORT');assert.equal(result.trailingPending,1);
 const broken=rows();broken[80].status='VOID_GAP';broken[80].outcomeUp=null;
 assert.equal(run(broken).status,'INSUFFICIENT');
 const skipped=rows();skipped.splice(50,1);
 assert.equal(run(skipped).status,'INSUFFICIENT');
});
test('rejects mixed feeds, duplicates, malformed probabilities and future settlements',()=>{
 const data=rows();
 assert.throws(()=>run([...data,{...data[0],sourceId:'other'}]),/identity/);
 assert.throws(()=>run([...data,{...data[0],id:'duplicate'}]),/Duplicate/);
 const invalid=rows();invalid[1].probability=NaN;
 assert.throws(()=>run(invalid),/Malformed/);
 const future=rows();
 assert.throws(()=>evaluateForwardReliability(future,feed,'v1',1,future[99].resolvedAt!-1),/future-dated/);
});
test('separates model versions and requires a full settled sample',()=>{
 const data=rows(1,100);
 const other={...data[0],id:'other',modelVersion:'v2'};
 assert.equal(run([...data,other]).status,'REPORT');
 assert.equal(evaluateForwardReliability(data,feed,'v2',1,asOf(data)).status,'INSUFFICIENT');
 assert.equal(run(rows(1,49),1,50).status,'INSUFFICIENT');
});
test('small or empty probability bins are explicit, and output is detached',()=>{
 const data=rows();data[0].probability=.1;
 const report=run(data);
 assert.equal(report.status,'REPORT');
 assert.equal(report.bins[0].count,1);
 assert.equal(report.bins[0].wilson95Lower,null);
 assert.equal(report.bins[1].count,0);
 report.bins[2].count=999;
 assert.equal(run(data).bins[2].count,99);
});
test('overdue pending forecasts fail closed; unresolved or backdated void events cannot be scored',()=>{
 const data=rows();
 const pending={...data.at(-1)!,id:'tail',baseStart:data.at(-1)!.baseStart+60,
   issuedAt:data.at(-1)!.issuedAt+60,targetStart:data.at(-1)!.targetStart+60,
   status:'PENDING' as const,resolvedAt:null,outcomeUp:null};
 const report=evaluateForwardReliability([...data,pending],feed,'v1',1,pending.targetStart+60);
 assert.equal(report.status,'INSUFFICIENT');
 assert.match(report.reason!,/Unresolved/);
 const voided=rows();voided[70].status='VOID_GAP';voided[70].outcomeUp=null;
 voided[70].resolvedAt=voided[70].issuedAt-1;
 assert.throws(()=>run(voided),/Malformed/);
});
