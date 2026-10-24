import {test} from 'node:test';
import assert from 'node:assert/strict';
import {evaluateForecastBlockSensitivity} from '../lib/forecast-block-sensitivity.ts';
import type {FeedIdentity,ForecastRecord} from '../lib/forward-forecast-ledger.ts';

const identity:FeedIdentity={instrument:'XAUUSD-FIXTURE',provider:'fixture',
  venue:'offline',sourceId:'A',priceSide:'bid',seconds:60};
const base=1800000000;
function records(outcomes:boolean[],horizon:1|3|12=1):ForecastRecord[]{
  return outcomes.map((up,i)=>{
    const start=base+i*horizon*60,targetStart=start+horizon*60;
    return {id:'f'+i,modelVersion:'v1',horizon,probability:.9,
      ...identity,baseStart:start,baseClose:100,issuedAt:start+61,
      targetStart,status:'SETTLED',resolvedAt:targetStart+61,
      outcomeUp:up,reason:null};
  });
}
const now=(r:ForecastRecord[])=>Math.max(...r.map(x=>x.targetStart+60))+5;
const evaluate=(r:ForecastRecord[],horizon:1|3|12=1,window=20,blockSize=5)=>
  evaluateForecastBlockSensitivity(r,identity,'v1',horizon,now(r),window,blockSize);

test('strong deterioration survives every paired contiguous block deletion',()=>{
  const r=records([...Array(20).fill(true),...Array(20).fill(false)]);
  const x=evaluate(r);
  assert.equal(x.status,'REPORT');assert.equal(x.live,false);
  assert.equal(x.comparisons,16);
  assert.ok(Math.abs(x.originalDeltaBrier!-.8)<1e-12);
  assert.ok(Math.abs(x.minDeltaBrier!-.8)<1e-12);
  assert.ok(Math.abs(x.maxDeltaBrier!-.8)<1e-12);
  assert.equal(x.allDeltaAtLeast002,true);
  assert.equal(x.allRecentAboveFixedBaseline,true);
});
test('stable correct predictions do not spuriously deteriorate',()=>{
  const x=evaluate(records(Array(40).fill(true)));
  assert.equal(x.status,'REPORT');
  assert.equal(x.allDeltaAtLeast002,false);
  assert.equal(x.allRecentAboveFixedBaseline,false);
  assert.equal(x.fractionDeltaAtLeast002,0);
});
test('isolated late outlier fails some block-deletion comparisons',()=>{
  const up=Array(40).fill(true);up[39]=false;
  const x=evaluate(records(up));
  assert.equal(x.status,'REPORT');
  assert.ok(x.originalDeltaBrier!>0.02);
  assert.ok(x.minDeltaBrier!<0.02);
  assert.ok(x.fractionDeltaAtLeast002!>0&&x.fractionDeltaAtLeast002!<1);
  assert.equal(x.allDeltaAtLeast002,false);
});
test('insufficient data remains unscored rather than invented',()=>{
  const r=records(Array(39).fill(true));
  const x=evaluate(r);
  assert.equal(x.status,'INSUFFICIENT');
  assert.equal(x.comparisons,0);assert.equal(x.minDeltaBrier,null);
});
test('voided outcome blocks comparison, not silently dropped',()=>{
  const r=records(Array(40).fill(true));
  r[20]={...r[20],status:'VOID_GAP',outcomeUp:null};
  const x=evaluate(r);
  assert.equal(x.status,'INSUFFICIENT');
});
test('mixed source and future issuance fail closed',()=>{
  const r=records(Array(40).fill(true));
  assert.throws(()=>evaluate([...r,{...r[0],provider:'other'}]));
  r[0]={...r[0],issuedAt:now(r)+1};
  assert.throws(()=>evaluate(r));
});
test('invalid block partitions fail closed',()=>{
  const r=records(Array(40).fill(true));
  for(const size of [0,1,3,7,10,2.5])
    assert.throws(()=>evaluate(r,1,20,size));
});
test('three-candle horizon retains phase isolation and deterministic result',()=>{
  const r=records([...Array(20).fill(true),...Array(20).fill(false)],3);
  const first=evaluate(r,3),second=evaluate(r,3);
  assert.deepEqual(first,second);
  assert.equal(first.status,'REPORT');
  assert.equal(first.comparisons,16);
});
test('other model versions cannot inflate selected observations',()=>{
  const r=records(Array(39).fill(true));
  const other={...r[0],id:'other',modelVersion:'v2'};
  const x=evaluate([...r,other]);
  assert.equal(x.status,'INSUFFICIENT');
});
