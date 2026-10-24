import {test} from 'node:test';
import assert from 'node:assert/strict';
import {backtest,DEFAULTS} from '../lib/backtest.ts';
import {runTimeBasedWalkForward} from '../lib/walk-forward.ts';
import type {ResearchRun} from '../lib/research-review.ts';
import type {Bar} from '../lib/research.ts';

function candles(n=1000):Bar[]{
 const out:Bar[]=[];
 for(let i=0;i<n;i++){
  const prior=i?out[i-1].close:100;
  const close=100+3*Math.sin(i*.17)+.003*i;
  out.push({time:1700000000+i*60,open:prior,high:Math.max(prior,close)+.4,
   low:Math.min(prior,close)-.4,close,volume:0,observed_minutes:1});
 }
 return out;
}
function fixture():ResearchRun{
 const bars=candles();
 const cfg={...DEFAULTS,lookback:8,atrPeriod:5,expiry:8,barSeconds:60};
 const report=backtest(bars,'A',cfg);
 return {id:'walk-forward-fixture',title:'Synthetic only',created_at:1700000000,
  payload:{reports:[report],splits:[],candles:bars,source:'synthetic test-only',
   datasetHash:'a'.repeat(64),
   window:{start:bars[0].time,end:bars.at(-1)!.time,bars:bars.length},
   notes:'No real market data'}};
}
test('three disjoint chronological forward windows with expanding past-only training',()=>{
 const x=runTimeBasedWalkForward(fixture(),'A');
 assert.equal(x.folds.length,3);
 assert.deepEqual(x.folds.map(f=>f.training.bars),[400,600,800]);
 assert.deepEqual(x.folds.map(f=>f.testing.bars),[200,200,200]);
 for(let i=0;i<x.folds.length;i++){
  const f=x.folds[i];
  assert.ok(f.training.end<=f.testing.start);
  assert.ok(x.candidates.includes(f.lookback));
  if(i>0)assert.ok(x.folds[i-1].testing.end<=f.testing.start);
 }
 assert.ok(x.warnings.some(w=>w.includes('not a locked')));
});
test('later test price edits cannot alter prior forward folds or past parameter selection',()=>{
 const a=fixture(),before=runTimeBasedWalkForward(a,'A');
 const b=fixture();
 for(const c of b.payload.candles!.slice(800)){
  c.open+=15;c.high+=15;c.low+=15;c.close+=15;
 }
 // This is a NEW internally consistent saved report; otherwise altered
 // candles must be rejected rather than silently attributed to the old run.
 b.payload.reports[0]=backtest(b.payload.candles!,'A',b.payload.reports[0].config!);
 const after=runTimeBasedWalkForward(b,'A');
 assert.deepEqual(after.folds.slice(0,2),before.folds.slice(0,2));
 assert.equal(after.folds[2].lookback,before.folds[2].lookback);
 assert.equal(after.folds[2].trainingAverageR,before.folds[2].trainingAverageR);
});
test('never selects a noisy lookback without sufficient training trades',()=>{
 const r=fixture(),x=runTimeBasedWalkForward(r,'A');
 for(const f of x.folds){
  if(f.selection==='DEFAULT_INSUFFICIENT_TRADES'){
   assert.equal(f.lookback,r.payload.reports[0].config!.lookback);
   assert.ok(f.warnings.some(w=>w.includes('without fitting')));
  }else assert.ok(f.trainingTrades>=30);
 }
});
test('rejects missing or contradictory snapshot, version and time coverage',()=>{
 const r=fixture();
 r.payload.candles=undefined;
 assert.throws(()=>runTimeBasedWalkForward(r,'A'),/no candle snapshot/);
 const s=fixture();s.payload.reports[0].ruleVersion='old-version';
 assert.throws(()=>runTimeBasedWalkForward(s,'A'),/version differs/);
 const t=fixture();t.payload.window!.bars=999;
 assert.throws(()=>runTimeBasedWalkForward(t,'A'),/coverage metadata/);
 const u=fixture();u.payload.candles![450].time=u.payload.candles![449].time;
 assert.throws(()=>runTimeBasedWalkForward(u,'A'),/not chronological/);
});
test('rejects thin chronological time windows instead of inventing missing history',()=>{
 const r=fixture();
 // A long gap forces time-quantile folds with insufficient coverage.
 for(let i=900;i<1000;i++)r.payload.candles![i].time+=60*10000;
 r.payload.window!.end=r.payload.candles!.at(-1)!.time;
 r.payload.reports[0]=backtest(r.payload.candles!,'A',r.payload.reports[0].config!);
 assert.throws(()=>runTimeBasedWalkForward(r,'A'),/lacks 200 training or 100 test candles/);
});

test('refuses forged saved metrics or a changed candle snapshot despite unchanged coverage',()=>{
 const r=fixture();
 r.payload.reports[0].metrics.netReturn+=2;
 assert.throws(()=>runTimeBasedWalkForward(r,'A'),/not reproducible/);
 const changed=fixture();
 changed.payload.candles![500].close+=.25;
 changed.payload.candles![500].high+=.25;
 assert.throws(()=>runTimeBasedWalkForward(changed,'A'),/not reproducible/);
});
test('refuses invalid saved reference lookbacks and mismatched report coverage',()=>{
 const r=fixture();
 r.payload.reports[0].config!.lookback=Infinity;
 assert.throws(()=>runTimeBasedWalkForward(r,'A'),/lookback/);
 const s=fixture();
 s.payload.reports[0].config!.lookback=2;
 assert.throws(()=>runTimeBasedWalkForward(s,'A'),/lookback/);
 const t=fixture();
 t.payload.reports[0].bars!+=1;
 assert.throws(()=>runTimeBasedWalkForward(t,'A'),/report coverage/);
});
test('reproducibility check does not alter saved candles or report metadata',()=>{
 const r=fixture(),before=structuredClone(r);
 const x=runTimeBasedWalkForward(r,'A');
 assert.equal(x.folds.length,3);
 assert.deepEqual(r,before);
});
