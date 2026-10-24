import {test} from 'node:test';
import assert from 'node:assert/strict';
import {studySweepConfluence} from '../lib/sweep-confluence-study.ts';
import type {Bar,Detection} from '../lib/research.ts';
const base=Date.UTC(2025,0,6)/1000,H=3600;
const bars=(n=12):Bar[]=>Array.from({length:n},(_,i)=>({time:base+i*H,
 open:100+i,high:102+i,low:99+i,close:101+i,volume:null,observed_minutes:60}));
const event=(kind:string,i:number,refs:number[]=[i-1]):Detection=>({kind,
 direction:kind.startsWith('SELL')||kind.startsWith('BULLISH')?'bullish observation':'bearish observation',
 observed_at:base+(i+1)*H,reference_times:refs.map(j=>base+j*H),
 level:100,explanation:'synthetic',rule_version:'structure-research-v3'});
const cfg={datasetId:'immutable-source-sha',instrument:'NSXUSD-CFD',frame:'1H',maxConfirmationBars:3,
 horizonBars:2,costScenariosBps:[0,5,15]};
const valid=[event('SELL-SIDE SWEEP',3,[1,3]),event('BULLISH STRUCTURE BREAK',5,[2,5]),event('BULLISH FVG',5,[3,4,5])];

test('strict same-close break + FVG enters only at following open with cost sensitivity',()=>{
 const r=studySweepConfluence(bars(),valid,cfg);
 assert.equal(r.sweepCount,1);assert.equal(r.confirmed,1);assert.equal(r.completed,1);
 assert.equal(r.signals[0].confirmationAt,base+6*H);
 assert.equal(r.signals[0].entryAt,base+6*H);
 assert.equal(r.signals[0].exitAt,base+8*H);
 assert.equal(r.signals[0].entry,106);assert.equal(r.signals[0].exit,108);
 assert.ok(Math.abs(r.signals[0].grossBps-(2/106*10000))<1e-7);
 assert.deepEqual(r.signals[0].netBps.map((x,i)=>x-r.signals[0].grossBps),[0,-5,-15]);
 assert.match(r.warning,/Not a validated MSS/);
});
test('opposite-direction, missing FVG or different-close events never confirm',()=>{
 for(const obs of [valid.slice(0,2),[valid[0],event('BEARISH STRUCTURE BREAK',5),valid[2]],
  [valid[0],valid[1],event('BULLISH FVG',6,[4,5,6])]]){
  const r=studySweepConfluence(bars(),obs,cfg);
  assert.equal(r.confirmed,0);assert.equal(r.unconfirmed,1);
 }
});
test('confirmation after fixed deadline does not use future information',()=>{
 const obs=[valid[0],event('BULLISH STRUCTURE BREAK',7,[4,7]),event('BULLISH FVG',7,[5,6,7])];
 assert.equal(studySweepConfluence(bars(),obs,cfg).confirmed,0);
});
test('incomplete candles or gaps invalidate confirmation and later outcome',()=>{
 const b=bars();b[4]={...b[4],observed_minutes:59};
 assert.throws(()=>studySweepConfluence(b,valid,cfg),/incomplete/);
 const c=bars();c[7]={...c[7],time:c[7].time+H};
 assert.throws(()=>studySweepConfluence(c,valid,cfg),/increasing/);
 const d=bars();d[7]={...d[7],observed_minutes:59};
 const r=studySweepConfluence(d,valid,cfg);
 assert.equal(r.confirmed,1);assert.equal(r.gapExcluded,1);assert.equal(r.completed,0);
});
test('cannot count a single confirmation twice',()=>{
 const r=studySweepConfluence(bars(),[event('SELL-SIDE SWEEP',2,[1,2]),...valid],cfg);
 assert.equal(r.sweepCount,2);assert.equal(r.confirmed,1);assert.equal(r.confirmationReused,1);
});
test('rejects invalid source, costs, future refs, duplicates and old rule versions',()=>{
 assert.throws(()=>studySweepConfluence(bars(),valid,{...cfg,datasetId:''}),/source identity/);
 assert.throws(()=>studySweepConfluence(bars(),valid,{...cfg,costScenariosBps:[5,5]}),/Cost scenarios/);
 assert.throws(()=>studySweepConfluence(bars(),valid,{...cfg,maxConfirmationBars:0}),/Confirmation window/);
 assert.throws(()=>studySweepConfluence(bars(),[...valid,valid[2]],cfg),/Duplicate/);
 assert.throws(()=>studySweepConfluence(bars(),[{...valid[0],rule_version:'v2'}],cfg),/causal v3/);
 assert.throws(()=>studySweepConfluence(bars(),[event('SELL-SIDE SWEEP',3,[4])],cfg),/future/);
});
test('event order and later candles cannot change already completed results',()=>{
 const a=studySweepConfluence(bars(9),valid,cfg);
 const b=studySweepConfluence(bars(12),[...valid].reverse(),cfg);
 assert.deepEqual(a.signals,b.signals);
});
test('pending confirmation outcome is not silently counted as loss',()=>{
 const r=studySweepConfluence(bars(7),valid,cfg);
 assert.equal(r.confirmed,1);assert.equal(r.pending,1);
 assert.equal(r.completed,0);assert.deepEqual(r.meanNetBps,[null,null,null]);
});
