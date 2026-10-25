import {test} from 'node:test';
import assert from 'node:assert/strict';
import {auditPairedForwardModels} from '../lib/paired-forward-model-audit.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';
const feed:FeedIdentity={instrument:'XAUUSD-TEST',provider:'synthetic',venue:'sandbox',sourceId:'A',priceSide:'bid',seconds:60};
const start=1800000000;
function fixtures(h:1|3|12=1,n=30):ForecastRecord[]{
 const rows:ForecastRecord[]=[];
 for(let i=0;i<n;i++){
  const baseStart=start+i*h*60;
  for(const modelVersion of ['A','B']){
   rows.push({...feed,id:`${modelVersion}-${h}-${i}`,modelVersion,horizon:h,
    probability:modelVersion==='A'?.7:.5,baseStart,baseClose:100,
    issuedAt:baseStart+60,targetStart:baseStart+h*60,
    status:'SETTLED',resolvedAt:baseStart+(h+1)*60,
    outcomeUp:i%3!==0,reason:null});
  }
 }
 return rows;
}
function audit(rows:ForecastRecord[],h:1|3|12=1,n=30,asOf?:number){
 return auditPairedForwardModels(rows,feed,'A','B',h,start,start+(n-1)*h*60,
  asOf??start+((n-1)*h+h+1)*60);
}
test('complete paired cohort reports descriptive losses without live capability',()=>{
 const r=audit(fixtures());
 assert.equal(r.status,'REPORT');assert.equal(r.expectedSlots,30);
 assert.equal(r.pairedSlots,30);assert.equal(r.brierB,.25);
 assert.equal(r.live,false);assert.equal(r.authenticated,false);
 assert.equal(r.execution,'NONE');assert.equal(r.persisted,false);
 assert.ok(r.blockDeltaBrierRange);
 assert.equal(r.aLowerLoss!+r.bLowerLoss!+r.tiedLoss!,30);
});
test('identical models have zero paired deltas and ties',()=>{
 const rows=fixtures().map(r=>({...r,probability:.5}));
 const r=audit(rows);assert.equal(r.deltaBrierAminusB,0);
 assert.equal(r.deltaLogLossAminusB,0);assert.equal(r.tiedLoss,30);
 assert.deepEqual(r.blockDeltaBrierRange,[0,0]);
});
test('direction of paired Brier difference is not a fabricated win rate',()=>{
 const rows=fixtures().map(r=>({...r,probability:r.modelVersion==='A'?.9:.1,outcomeUp:true}));
 const r=audit(rows);assert.ok(r.deltaBrierAminusB!<0);
 assert.equal(r.aLowerLoss,30);assert.equal(r.bLowerLoss,0);
 assert.equal(r.blockDeltaBrierRange![0],r.blockDeltaBrierRange![1]);
});
test('all horizons retain disjoint fixed UTC phase and own scores',()=>{
 for(const h of [1,3,12] as const){const r=audit(fixtures(h),h);
  assert.equal(r.status,'REPORT');assert.equal(r.horizon,h);
 }
});
test('missing either model issue prevents survivorship-biased score',()=>{
 const rows=fixtures().filter(r=>r.id!=='B-1-5');
 const r=audit(rows);assert.equal(r.status,'INSUFFICIENT');
 assert.match(r.reason!,/Missing/);assert.equal(r.brierA,null);
});
test('void and pending outcomes are not silently excluded',()=>{
 const voided=fixtures();voided[5]={...voided[5],status:'VOID_GAP',outcomeUp:null,reason:'gap'};
 assert.match(audit(voided).reason!,/Pending or gap/);
 const pending=fixtures();pending[8]={...pending[8],status:'PENDING',resolvedAt:null,outcomeUp:null};
 assert.equal(audit(pending).status,'INSUFFICIENT');
});
test('immature target cohort fails closed, not scored as settled',()=>{
 const rows=fixtures();
 for(let i=rows.length-2;i<rows.length;i++)rows[i]={...rows[i],status:'PENDING',resolvedAt:null,outcomeUp:null};
 const r=audit(rows,1,30,start+30*60);
 assert.equal(r.status,'INSUFFICIENT');assert.match(r.reason!,/immature/);
});
test('late receipt on either side blocks scoring',()=>{
 const rows=fixtures();rows[3]={...rows[3],resolvedAt:rows[3].resolvedAt!+121};
 assert.match(audit(rows,1,30,start+20000).reason!,/Late settlement/);
});
test('conflicting outcome and base price cannot be compared',()=>{
 const rows=fixtures();rows[1]={...rows[1],outcomeUp:!rows[1].outcomeUp};
 assert.throws(()=>audit(rows),/Conflicting/);
 const prices=fixtures();prices[1]={...prices[1],baseClose:101};
 assert.throws(()=>audit(prices),/Conflicting/);
});
test('duplicate model slot or record ID rejected',()=>{
 const rows=fixtures();
 assert.throws(()=>audit([...rows,{...rows[0],id:'other'}]),/Duplicate/);
 assert.throws(()=>audit([...rows,{...rows[0],modelVersion:'B'}]),/Duplicate/);
});
test('mixed feeds, unaligned and out-of-cohort records rejected',()=>{
 const rows=fixtures();
 assert.throws(()=>audit([...rows,{...rows[0],sourceId:'other'}]),/source/);
 const unaligned=fixtures();unaligned[0]={...unaligned[0],baseStart:start+1};
 assert.throws(()=>audit(unaligned),/Malformed/);
 const beyond=fixtures();beyond[0]={...beyond[0],baseStart:start-60};
 assert.throws(()=>audit(beyond),/Malformed/);
});
test('future issue, retroactive issue, premature settlement and invalid probability fail',()=>{
 const future=fixtures();future[0]={...future[0],issuedAt:start+100000};
 assert.throws(()=>audit(future),/Malformed/);
 const retro=fixtures();retro[0]={...retro[0],issuedAt:start+120};
 assert.throws(()=>audit(retro),/Malformed/);
 const premature=fixtures();premature[0]={...premature[0],resolvedAt:start+60};
 assert.throws(()=>audit(premature),/Malformed/);
 const nan=fixtures();nan[0]={...nan[0],probability:NaN};
 assert.throws(()=>audit(nan),/Malformed/);
});
test('other model/horizon records never contaminate paired scores',()=>{
 const rows=fixtures();const extra={...rows[0],id:'C',modelVersion:'C',probability:.01};
 const extraH={...rows[0],id:'otherH',horizon:3 as const,targetStart:start+180};
 assert.deepEqual(audit([...rows,extra,extraH]),audit(rows));
});
test('sample size and phase restrictions prevent convenient post hoc windows',()=>{
 assert.equal(audit(fixtures(1,4),1,4).status,'INSUFFICIENT');
 assert.throws(()=>auditPairedForwardModels(fixtures(),feed,'A','A',1,start,start+29*60,start+99999),/configuration/);
 assert.throws(()=>auditPairedForwardModels(fixtures(),feed,'A','B',3,start,start+29*60,start+99999),/window/);
 assert.throws(()=>auditPairedForwardModels([],feed,'A','B',1,start,start+5000*60,start+999999),/capacity/);
});
test('inputs and output are detached and deterministic',()=>{
 const rows=fixtures();const snapshot=JSON.stringify(rows);
 const a=audit(rows);a.blockDeltaBrierRange![0]=99;
 assert.equal(JSON.stringify(rows),snapshot);
 assert.deepEqual(audit(rows),audit(fixtures()));
});
