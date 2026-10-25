import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditForecastCalibrationEProcess} from '../lib/forecast-calibration-eprocess.ts';
import type {EProcessRecord,EProcessFeed} from '../lib/forecast-calibration-eprocess.ts';
const feed:EProcessFeed={instrument:'XAUUSD-SYNTHETIC',provider:'fixture',venue:'offline',sourceId:'A',priceSide:'bid',seconds:60};
const start=1800000000;
function cohort(n=40,h:1|3|12=1,p=.5,up=(i:number)=>i%2===0):EProcessRecord[]{
 return Array.from({length:n},(_,i)=>{
  const baseStart=start+i*h*60,targetStart=baseStart+h*60;
  return {...feed,id:`id_${i}`,modelVersion:'v1',horizon:h,probability:p,
    baseStart,baseClose:100,issuedAt:baseStart+60,targetStart,
    status:'SETTLED',resolvedAt:targetStart+60,outcomeUp:up(i),reason:null};
 });
}
const audit=(r:EProcessRecord[],h:1|3|12=1)=>auditForecastCalibrationEProcess(r,feed,'v1',h,r.at(-1)!.resolvedAt!+1);
test('well-calibrated alternating synthetic data does not trigger review',()=>{
 const x=audit(cohort());assert.equal(x.status,'REPORT');assert.equal(x.decision,'NO_THRESHOLD');
 assert.equal(x.live,false);assert.equal(x.execution,'NONE');assert.equal(x.observations,40);
});
test('strongly wrong fixed probabilities trigger anytime review',()=>{
 const x=audit(cohort(40,1,.95,()=>false));assert.equal(x.status,'REPORT');
 assert.equal(x.decision,'REVIEW_ONLY');assert.ok(x.peakLogE!>x.thresholdLogE);
});
test('fixed family size changes threshold but never authorizes alerts',()=>{
 const r=cohort(40,1,.95,()=>false),asOf=r.at(-1)!.resolvedAt!+1;
 const a=auditForecastCalibrationEProcess(r,feed,'v1',1,asOf,{familySize:1});
 const b=auditForecastCalibrationEProcess(r,feed,'v1',1,asOf,{familySize:20});
 assert.ok(b.thresholdLogE>a.thresholdLogE);assert.equal(a.alertsEnabled,false);
});
test('too few declared observations return insufficient',()=>{
 const r=cohort(29);const x=audit(r);assert.equal(x.status,'INSUFFICIENT');assert.equal(x.finalLogE,null);
});
test('missing slot and reversed records fail closed',()=>{
 const r=cohort();r.splice(5,1);assert.throws(()=>audit(r),/noncontiguous/);
 const s=cohort();[s[5],s[6]]=[s[6],s[5]];assert.throws(()=>audit(s),/noncontiguous/);
});
test('duplicate IDs and mixed source/price side fail closed',()=>{
 const r=cohort();r[8].id=r[0].id;assert.throws(()=>audit(r),/mixed/);
 const s=cohort();s[8].sourceId='B';assert.throws(()=>audit(s),/mixed/);
 const t=cohort();t[8].priceSide='ask';assert.throws(()=>audit(t),/mixed/);
});
test('void, pending and missing outcomes never silently score',()=>{
 for(const status of ['PENDING','VOID_GAP'] as const){const r=cohort();r[9].status=status;
  assert.throws(()=>audit(r),/noncausal/);}
 const r=cohort();r[9].outcomeUp=null;assert.throws(()=>audit(r),/noncausal/);
});
test('future and delayed settlement rejected',()=>{
 const r=cohort();r[4].resolvedAt!+=121;assert.throws(()=>audit(r),/late/);
 const s=cohort();s[39].resolvedAt!+=200;assert.throws(()=>audit(s),/late/);
 const t=cohort();assert.throws(()=>auditForecastCalibrationEProcess(t,feed,'v1',1,t[39].issuedAt),/noncausal/);
});
test('no settlement knowledge at next issuance means no predictable update',()=>{
 const r=cohort();r[0].resolvedAt!+=20;
 assert.throws(()=>audit(r),/noncausal/);
});
test('horizons 3 and 12 use separate nonoverlapping phases',()=>{
 for(const h of [3,12] as const){const r=cohort(40,h);const x=audit(r,h);
  assert.equal(x.status,'REPORT');assert.equal(x.horizon,h);}
});
test('invalid configuration and probabilities rejected',()=>{
 const r=cohort(),t=r.at(-1)!.resolvedAt!+1;
 for(const alpha of [0,1,NaN])assert.throws(()=>auditForecastCalibrationEProcess(r,feed,'v1',1,t,{alpha}),/configuration/);
 for(const familySize of [0,101,1.2])assert.throws(()=>auditForecastCalibrationEProcess(r,feed,'v1',1,t,{familySize}),/configuration/);
 const s=cohort();s[2].probability=1;assert.throws(()=>audit(s),/noncausal/);
});
test('deterministic replay and no broker order capability',()=>{
 const r=cohort(40,1,.95,()=>false);assert.deepEqual(audit(r),audit(r));
 assert.equal(audit(r).persisted,false);assert.equal(audit(r).authenticated,false);
});
test('rejects later outcome leaking into earlier forecast',()=>{
 const r=cohort();r[5].issuedAt=r[5].targetStart+60;
 assert.throws(()=>audit(r),/noncausal/);
});
