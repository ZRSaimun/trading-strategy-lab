import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditForecastCalibrationDrift} from '../lib/forecast-calibration-drift.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';
const feed:FeedIdentity={instrument:'XAUUSD-FIXTURE',provider:'synthetic',venue:'offline',sourceId:'A',priceSide:'bid',seconds:60};
const start=1800000000;
function rows(n=100,h:1|3|12=1,p=.9):ForecastRecord[]{
  return Array.from({length:n},(_,i)=>{
    const baseStart=start+i*h*60,targetStart=baseStart+h*60;
    return {...feed,id:'f'+i,modelVersion:'v1',horizon:h,probability:p,
      baseStart,baseClose:100,issuedAt:baseStart+60,targetStart,
      status:'SETTLED',resolvedAt:targetStart+60,outcomeUp:true,reason:null};
  });
}
const run=(r:ForecastRecord[],h:1|3|12=1,n=50)=>auditForecastCalibrationDrift(
  r.slice(0,n),r.slice(n),feed,'v1',h,r.at(-1)!.resolvedAt!+10,n);

test('detects simultaneous calibration and Brier deterioration',()=>{
 const r=rows();for(let i=50;i<100;i++)r[i].outcomeUp=false;
 const x=run(r);
 assert.equal(x.status,'REPORT');assert.equal(x.review,'CALIBRATION_AND_LOSS_REVIEW');
 assert.ok(x.deltaBrier!>0.7);assert.ok(x.deltaECE!>0.7);
 assert.equal(x.live,false);assert.equal(x.execution,'NONE');
});
test('stable synthetic data has no threshold crossing',()=>{
 const x=run(rows());assert.equal(x.status,'REPORT');
 assert.equal(x.review,'NO_THRESHOLD_CROSSING');assert.equal(x.deltaBrier,0);
 assert.equal(x.deltaECE,0);
});
test('weak baseline can worsen loss without ECE rise',()=>{
 const r=rows(100,1,.5);for(let i=0;i<50;i++)r[i].outcomeUp=i%2===0;
 for(let i=50;i<100;i++)r[i].probability=.51;
 const x=run(r);assert.equal(x.status,'REPORT');
 assert.equal(x.review,'NO_THRESHOLD_CROSSING');
});
test('genuine missing declared slot fails closed',()=>{
 const r=rows();r.splice(20,1);
 assert.throws(()=>run(r),/Discontinuous/);
});
test('missing tail returns insufficient instead of selected-sample score',()=>{
 const r=rows(99);const x=auditForecastCalibrationDrift(r.slice(0,50),r.slice(50),feed,'v1',1,r.at(-1)!.resolvedAt!+10);
 assert.equal(x.status,'INSUFFICIENT');assert.equal(x.review,'NONE');
 assert.equal(x.deltaBrier,null);
});
test('out-of-order and overlap rejected',()=>{
 const r=rows();[r[50],r[51]]=[r[51],r[50]];
 assert.throws(()=>run(r),/Discontinuous/);
});
test('source drift, version drift, and duplicate IDs rejected',()=>{
 const r=rows();r[60].sourceId='other';assert.throws(()=>run(r),/identity/);
 const v=rows();v[60].modelVersion='v2';assert.throws(()=>run(v),/identity/);
 const d=rows();d[60].id=d[1].id;assert.throws(()=>run(d),/identity/);
});
test('voided and overdue pending outcome cannot produce drift',()=>{
 const r=rows();r[70].status='VOID_GAP';r[70].outcomeUp=null;
 assert.equal(run(r).status,'INSUFFICIENT');
 const p=rows();p[70].status='PENDING';p[70].resolvedAt=null;p[70].outcomeUp=null;
 assert.equal(run(p).status,'INSUFFICIENT');
});
test('future settlement rejected rather than scored',()=>{
 const r=rows();r[75].resolvedAt=r[99].resolvedAt!+100;
 assert.throws(()=>run(r),/future-dated/);
});
test('horizons 3 and 12 maintain nonoverlapping phase and chronology',()=>{
 for(const h of [3,12] as const){const r=rows(100,h);
  const x=run(r,h);assert.equal(x.status,'REPORT');
  assert.equal(x.horizon,h);assert.ok(x.recentLastTargetClose!>x.earlierLastTargetClose!);
 }
});
test('invalid sample bounds and timestamp rejected',()=>{
 const r=rows();for(const n of [0,49,251,50.5])assert.throws(()=>auditForecastCalibrationDrift(r.slice(0,50),r.slice(50),feed,'v1',1,r[99].resolvedAt!,n),/configuration/);
 assert.throws(()=>auditForecastCalibrationDrift(r.slice(0,50),r.slice(50),feed,'v1',1,NaN),/configuration/);
});
test('mixed price side cannot masquerade as identical feed',()=>{
 const r=rows();r[5].priceSide='ask';assert.throws(()=>run(r),/identity/);
});

test('loss-only review separates ECE from Brier worsening',()=>{
 const r=rows();for(let i=0;i<100;i++)r[i].outcomeUp=i%2===0;
 for(let i=50;i<100;i++)r[i].probability=.94;
 const x=run(r);assert.equal(x.status,'REPORT');
 assert.equal(x.review,'LOSS_REVIEW');
 assert.ok(x.deltaBrier!>=.02&&x.deltaECE!<.05);
});
test('late settlement is insufficient, never silently scored',()=>{
 const r=rows();r[30].resolvedAt!+=121;
 const x=run(r);assert.equal(x.status,'INSUFFICIENT');
 assert.match(x.reason!,/late/);
});
