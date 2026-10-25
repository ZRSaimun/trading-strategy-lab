import {test} from 'node:test';
import assert from 'node:assert/strict';
import {assessOfflineForecastAgreement as assess} from '../lib/forecast-agreement-gate.ts';
import type {CausalFrequencyBaseline} from '../lib/causal-frequency-baseline.ts';
import type {EwmaForecast} from '../lib/causal-ewma-frequency.ts';
const identity={instrument:'FIXTURE-GOLD',provider:'synthetic',venue:'test',sourceId:'A',priceSide:'bid' as const,seconds:60};
const base=1800000000;
function pair(a=0.8,b=0.75){
 const f:CausalFrequencyBaseline={mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,execution:'NONE',quoteTimestamp:null,
   modelVersion:'jeffreys-frequency-v1',identity:{...identity},baseStart:base,issuedAsOf:base+61,
   horizons:([1,3,12] as const).map(h=>({horizon:h,status:'READY_OFFLINE_ONLY' as const,samples:60,up:40,
     probabilityUp:a,earliestOutcomeClose:base-3600,latestOutcomeClose:base+60}))};
 const e:EwmaForecast={mode:'UNVERIFIED_LOCAL_RESEARCH',live:false,persisted:false,execution:'NONE',quoteTimestamp:null,
   modelVersion:'ewma-frequency-v1',identity:{...identity},baseStart:base,issuedAsOf:base+61,
   halfLifeSamples:20,minEffectiveSamples:10,
   horizons:([1,3,12] as const).map(h=>({horizon:h,status:'READY_OFFLINE_ONLY' as const,samples:60,up:40,
     effectiveSamples:35,weightedUpRate:b,probabilityUp:b,latestOutcomeClose:base+60}))};
 return {f,e};
}
test('consensus up is research-only and never enables orders or alerts',()=>{
 const {f,e}=pair(),x=assess(f,e,base+61);
 assert.deepEqual(x.horizons.map(h=>h.status),Array(3).fill('CONSENSUS_UP_RESEARCH_ONLY'));
 assert.deepEqual([x.live,x.authenticated,x.persisted,x.alertsEnabled,x.execution,x.ordersSubmitted],
   [false,false,false,false,'NONE',0]);
 assert.deepEqual(x.horizons[0].probabilityRange,[0.75,0.8]);
});
test('down consensus stays descriptive',()=>{
 const {f,e}=pair(0.2,0.25);assert.equal(assess(f,e,base+61).horizons[0].direction,'DOWN');
});
test('opposing directional estimates abstain',()=>{
 const {f,e}=pair(0.55,0.45);assert.equal(assess(f,e,base+61).horizons[0].status,'ABSTAIN_CONFLICT');
});
test('large model disagreement abstains even when directions agree',()=>{
 const {f,e}=pair(0.9,0.65);assert.equal(assess(f,e,base+61).horizons[0].status,'ABSTAIN_CONFLICT');
});
test('weak directional margins abstain',()=>{
 const {f,e}=pair(0.54,0.53);assert.equal(assess(f,e,base+61).horizons[0].status,'ABSTAIN_UNCERTAIN');
});
test('insufficient horizon never inherits consensus from other horizons',()=>{
 const {f,e}=pair();f.horizons[2].status='INSUFFICIENT';f.horizons[2].probabilityUp=null;
 e.horizons[2].status='INSUFFICIENT';e.horizons[2].probabilityUp=null;
 assert.equal(assess(f,e,base+61).horizons[2].status,'ABSTAIN_INSUFFICIENT');
 assert.equal(assess(f,e,base+61).horizons[0].direction,'UP');
});
test('rejects mismatched source and base-candle identities',()=>{
 const {f,e}=pair();e.identity={...e.identity,sourceId:'B'};assert.throws(()=>assess(f,e,base+61));
 e.identity={...f.identity};e.baseStart++;assert.throws(()=>assess(f,e,base+61));
});
test('rejects mismatched issuance, future and expired assessment',()=>{
 const {f,e}=pair();e.issuedAsOf++;assert.throws(()=>assess(f,e,base+61));
 e.issuedAsOf=f.issuedAsOf;assert.throws(()=>assess(f,e,base+60));
 assert.throws(()=>assess(f,e,base+200));
});
test('rejects mixed horizon order and fabricated sample counts',()=>{
 const {f,e}=pair();e.horizons.reverse();assert.throws(()=>assess(f,e,base+61));
 e.horizons.reverse();e.horizons[0].samples=70;assert.throws(()=>assess(f,e,base+61));
});
test('rejects nonfinite, invalid or contradictory probability states',()=>{
 for(const p of [NaN,Infinity,-0.01,1.01]){
   const {f,e}=pair();f.horizons[0].probabilityUp=p;assert.throws(()=>assess(f,e,base+61));
 }
 const {f,e}=pair();e.horizons[0].probabilityUp=null;assert.throws(()=>assess(f,e,base+61));
});
test('rejects invalid policy values and caller-mutated research flags',()=>{
 const {f,e}=pair();
 for(const c of [{maxDisagreement:0},{maxDisagreement:0.51},{minDirectionalMargin:0.5},
                 {minDirectionalMargin:-1},{maxAssessmentLagSeconds:-1}])
  assert.throws(()=>assess(f,e,base+61,c));
 (e as unknown as {live:boolean}).live=true;assert.throws(()=>assess(f,e,base+61));
});
test('deterministic without mutating source records',()=>{
 const {f,e}=pair(),before=JSON.stringify([f,e]);
 assert.deepEqual(assess(f,e,base+61),assess(f,e,base+61));
 assert.equal(JSON.stringify([f,e]),before);
});
