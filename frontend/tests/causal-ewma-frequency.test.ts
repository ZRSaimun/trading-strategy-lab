import {test} from 'node:test';
import assert from 'node:assert/strict';
import {estimateCausalEwmaFrequency as estimate} from '../lib/causal-ewma-frequency.ts';
import {estimateCausalFrequencyBaseline} from '../lib/causal-frequency-baseline.ts';
import type {ReceivedCompletedCandle} from '../lib/causal-frequency-baseline.ts';
import type {FeedIdentity} from '../lib/forward-forecast-ledger.ts';

const identity:FeedIdentity={
  instrument:'FIXTURE-XAUUSD',provider:'fixture',venue:'test',
  sourceId:'A',priceSide:'bid',seconds:60,
};
const origin=1800000000;
function series(n=400):ReceivedCompletedCandle[]{
  return Array.from({length:n},(_,i)=>({
    identity:{...identity},
    start:origin+i*60,
    close:1000+i*0.1+Math.sin(i/5),
    receivedAt:origin+(i+1)*60+1,
  }));
}
const clock=(rows:readonly ReceivedCompletedCandle[])=>
  rows[rows.length-1].receivedAt;
test('reports all three disjoint horizons, never an executable signal',()=>{
  const rows=series();
  const x=estimate(rows,clock(rows));
  assert.deepEqual(x.horizons.map(h=>h.horizon),[1,3,12]);
  assert.ok(x.horizons.every(h=>h.status==='READY_OFFLINE_ONLY'));
  assert.ok(x.horizons.every(h=>h.probabilityUp!>0&&h.probabilityUp!<1));
  assert.deepEqual([x.live,x.persisted,x.execution,x.quoteTimestamp],
    [false,false,'NONE',null]);
  assert.equal(x.mode,'UNVERIFIED_LOCAL_RESEARCH');
});
test('fixed disjoint h-step samples do not overlap within each horizon',()=>{
  const rows=series(400),x=estimate(rows,clock(rows),{maxSamples:200});
  assert.equal(x.horizons[0].samples,200);
  assert.equal(x.horizons[1].samples,133);
  assert.equal(x.horizons[2].samples,33);
  assert.equal(x.horizons[2].latestOutcomeClose,rows.at(-1)!.start+60);
});
test('recent completed directional regime gets higher weight than old outcomes',()=>{
  const rows=series(400).map((r,i)=>({
    ...r,close:i<330?1000-i:670+(i-329)*2,
  }));
  const ewma=estimate(rows,clock(rows),{halfLifeSamples:8,maxSamples:120});
  const unweighted=estimateCausalFrequencyBaseline(rows,clock(rows),{
    minSamples:20,maxSamples:120,
  });
  assert.ok(ewma.horizons[0].probabilityUp!>
    unweighted.horizons[0].probabilityUp!);
});
test('smaller half-life reacts more strongly to recent completed outcomes',()=>{
  const rows=series(400).map((r,i)=>({
    ...r,close:i<330?1000-i:670+(i-329)*2,
  }));
  const fast=estimate(rows,clock(rows),{halfLifeSamples:5});
  const slow=estimate(rows,clock(rows),{halfLifeSamples:80});
  assert.ok(fast.horizons[0].probabilityUp!>slow.horizons[0].probabilityUp!);
});
test('effective sample size can force abstention even with many observations',()=>{
  const rows=series(400);
  const x=estimate(rows,clock(rows),{
    halfLifeSamples:2,minEffectiveSamples:20,
  });
  assert.ok(x.horizons.every(h=>h.status==='INSUFFICIENT'));
  assert.ok(x.horizons.every(h=>h.probabilityUp===null));
});
test('not enough 12-step outcomes means no 12-step forecast',()=>{
  const rows=series(100),x=estimate(rows,clock(rows));
  assert.equal(x.horizons[0].status,'READY_OFFLINE_ONLY');
  assert.equal(x.horizons[2].status,'INSUFFICIENT');
  assert.equal(x.horizons[2].probabilityUp,null);
});
test('changing an interior non-boundary close cannot affect the 12-step outcome',()=>{
  const rows=series(400),altered=rows.map(r=>({...r}));
  altered[398]={...altered[398],close:altered[398].close+100};
  const a=estimate(rows,clock(rows)),b=estimate(altered,clock(altered));
  assert.equal(a.horizons[2].probabilityUp,b.horizons[2].probabilityUp);
  assert.notEqual(a.horizons[0].probabilityUp,b.horizons[0].probabilityUp);
});
test('mixed provider identity, missing minute and revised timestamps fail closed',()=>{
  const rows=series();
  const mixed=rows.map(r=>({...r}));
  mixed[20]={...mixed[20],identity:{...identity,sourceId:'B'}};
  assert.throws(()=>estimate(mixed,clock(mixed)));
  const missing=rows.filter((_,i)=>i!==20);
  assert.throws(()=>estimate(missing,clock(missing)));
  const reversed=rows.map(r=>({...r}));
  reversed[20]={...reversed[20],receivedAt:reversed[19].receivedAt-1};
  assert.throws(()=>estimate(reversed,clock(reversed)));
});
test('stale, future and retroactive observation timestamps fail closed',()=>{
  const rows=series();
  assert.throws(()=>estimate(rows,clock(rows)-1));
  assert.throws(()=>estimate(rows,clock(rows)+500));
  const future=rows.map(r=>({...r}));
  future[20]={...future[20],receivedAt:future[20].start+59};
  assert.throws(()=>estimate(future,clock(future)));
});
test('reject invalid configuration rather than returning confident probabilities',()=>{
  const rows=series();
  for(const config of [
    {halfLifeSamples:1},{halfLifeSamples:501},
    {minSamples:19},{maxSamples:19},
    {minEffectiveSamples:9},{minEffectiveSamples:2001},
    {maxSamples:2001},
  ])assert.throws(()=>estimate(rows,clock(rows),config));
});
test('deterministic results do not mutate caller inputs',()=>{
  const rows=series(),before=JSON.stringify(rows);
  assert.deepEqual(estimate(rows,clock(rows)),estimate(rows,clock(rows)));
  assert.equal(JSON.stringify(rows),before);
});
